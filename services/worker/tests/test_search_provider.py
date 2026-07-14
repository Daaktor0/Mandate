from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from mandate_worker.fixtures import AdapterCapability, FixtureCatalog
from mandate_worker.providers.search import (
    ExaHttpTransport,
    ExaSearchProvider,
    FixtureSearchProvider,
    SearchConfigurationError,
    SearchHttpResponse,
    SearchProviderError,
    SearchRequest,
    build_search_provider,
)
from mandate_worker.runtime import build_runtime_adapter_plan
from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPOSITORY_ROOT / "fixtures" / "demo"


class StubExaTransport:
    def __init__(self, responses: list[SearchHttpResponse]) -> None:
        self.responses = responses
        self.payloads: list[Mapping[str, object]] = []

    async def post_json(self, payload: Mapping[str, object]) -> SearchHttpResponse:
        self.payloads.append(payload)
        return self.responses.pop(0)


def response(payload: object, *, status: int = 200) -> SearchHttpResponse:
    return SearchHttpResponse(
        status_code=status,
        content_type="application/json",
        body=json.dumps(payload).encode(),
    )


def valid_exa_payload() -> dict[str, object]:
    return {
        "requestId": "request-1",
        "results": [
            {
                "title": "Official company page",
                "url": "https://example.com/about#team",
                "id": "https://example.com/about",
                "publishedDate": "2026-07-01T10:00:00Z",
                "author": "Example Limited",
                "highlights": ["Public business description."],
            },
            {
                "title": "Duplicate result",
                "url": "https://example.com/about",
                "id": "duplicate",
                "highlights": ["Duplicate should be removed."],
            },
        ],
        "costDollars": {"total": 0.007, "search": {"neural": 0.007}},
    }


def test_INTAKE_04_search_request_rejects_non_public_context_fields() -> None:
    with pytest.raises(ValidationError):
        SearchRequest.model_validate(
            {
                "query": "Example Limited official website",
                "limit": 5,
                "user_id": "forbidden",
                "firm": "forbidden",
                "billing": "forbidden",
                "matter_narrative": "forbidden",
            }
        )


def test_RUN_07_search_request_bounds_and_normalises_filters() -> None:
    request = SearchRequest(
        query="  Example   Limited   official website ",
        limit=20,
        include_domains=("EXAMPLE.COM.",),
        exclude_domains=("news.example",),
        start_published_at=datetime(2025, 1, 1, tzinfo=UTC),
        end_published_at=datetime(2026, 7, 15, tzinfo=UTC),
    )

    assert request.query == "Example Limited official website"
    assert request.include_domains == ("example.com",)
    assert request.exclude_domains == ("news.example",)


@pytest.mark.asyncio
async def test_NFR_03_fixture_search_is_deterministic_and_zero_spend() -> None:
    catalog = FixtureCatalog.load(FIXTURE_ROOT)
    provider = FixtureSearchProvider.from_catalog(catalog)

    matching = await provider.search(SearchRequest(query="Mandate demo company"))
    missing = await provider.search(SearchRequest(query="Another company"))

    assert matching.provider == "fixture"
    assert matching.fixture is True
    assert matching.provider_calls == 0
    assert matching.cost_usd == 0
    assert len(matching.results) == 1
    assert matching.results[0].url == "https://mandate-demo.example/about"
    assert matching.results[0].highlights == (
        "Synthetic public-information search result for offline tests.",
    )
    assert missing.results == ()


@pytest.mark.asyncio
async def test_RUN_06_exa_payload_is_extract_only_and_privacy_allowlisted() -> None:
    transport = StubExaTransport([response(valid_exa_payload())])
    provider = ExaSearchProvider(transport)
    request = SearchRequest(
        query="Example Limited official regulatory filings",
        limit=5,
        include_domains=("example.com",),
    )

    result = await provider.search(request)

    assert result.provider == "exa"
    assert result.fixture is False
    assert result.provider_calls == 1
    assert result.cost_usd == 0.007
    assert len(result.results) == 1
    assert result.results[0].url == "https://example.com/about"
    assert result.results[0].published_at == datetime(2026, 7, 1, 10, tzinfo=UTC)

    payload = dict(transport.payloads[0])
    assert payload == {
        "query": "Example Limited official regulatory filings",
        "type": "auto",
        "numResults": 5,
        "moderation": True,
        "contents": {
            "highlights": {
                "query": "Example Limited official regulatory filings",
                "maxCharacters": 2000,
            }
        },
        "includeDomains": ["example.com"],
    }
    payload_text = json.dumps(payload).casefold()
    assert "summary" not in payload_text
    assert '"text"' not in payload_text
    assert "context" not in payload_text
    assert "user_id" not in payload_text
    assert "billing" not in payload_text
    assert "letterhead" not in payload_text


@pytest.mark.asyncio
async def test_RUN_07_exa_retries_one_rate_limit_then_reports_call_count() -> None:
    transport = StubExaTransport(
        [
            response({"error": "rate limited"}, status=429),
            response(valid_exa_payload()),
        ]
    )

    async def no_delay(_: float) -> None:
        return None

    provider = ExaSearchProvider(transport, retry_delay=no_delay)
    result = await provider.search(SearchRequest(query="Example Limited"))

    assert result.provider_calls == 2
    assert len(transport.payloads) == 2


@pytest.mark.asyncio
async def test_RUN_06_exa_rejects_invalid_content_type_without_retry() -> None:
    transport = StubExaTransport(
        [
            SearchHttpResponse(
                status_code=200,
                content_type="text/html",
                body=b"<html>not json</html>",
            )
        ]
    )
    provider = ExaSearchProvider(transport)

    with pytest.raises(SearchProviderError) as captured:
        await provider.search(SearchRequest(query="Example Limited"))

    assert captured.value.code == "search_response_invalid"
    assert captured.value.retryable is False
    assert len(transport.payloads) == 1


@pytest.mark.asyncio
async def test_SEC_03_exa_result_url_cannot_contain_credentials_or_non_default_port() -> None:
    bad_payload = valid_exa_payload()
    results = bad_payload["results"]
    assert isinstance(results, list)
    first = results[0]
    assert isinstance(first, dict)
    first["url"] = "https://user:password@example.com:8443/private"
    transport = StubExaTransport([response(bad_payload)])
    provider = ExaSearchProvider(transport)

    with pytest.raises(SearchProviderError) as captured:
        await provider.search(SearchRequest(query="Example Limited"))

    assert captured.value.code == "search_response_invalid"
    assert captured.value.retryable is False


def test_SEC_09_exa_http_transport_hides_api_key_from_repr() -> None:
    transport = ExaHttpTransport("exa-secret-value")

    assert "exa-secret-value" not in repr(transport)


def test_NFR_03_builder_requires_demo_mode_for_fixture() -> None:
    plan = build_runtime_adapter_plan(
        {"DEMO_MODE": "0", "PROVIDER_SEARCH": "fixture"},
        fixture_root=FIXTURE_ROOT,
    )

    with pytest.raises(SearchConfigurationError, match="search_fixture_requires_demo_mode"):
        build_search_provider(plan)


def test_NFR_03_builder_requires_exa_key_without_fallback() -> None:
    plan = build_runtime_adapter_plan(
        {"DEMO_MODE": "0", "PROVIDER_SEARCH": "exa"},
        fixture_root=FIXTURE_ROOT,
    )

    with pytest.raises(SearchConfigurationError, match="search_credentials_missing"):
        build_search_provider(plan, environ={})


def test_NFR_03_builder_uses_injected_exa_transport_without_reading_a_key() -> None:
    plan = build_runtime_adapter_plan(
        {"DEMO_MODE": "0", "PROVIDER_SEARCH": "exa"},
        fixture_root=FIXTURE_ROOT,
    )
    transport = StubExaTransport([response(valid_exa_payload())])

    provider = build_search_provider(plan, environ={}, exa_transport=transport)

    assert isinstance(provider, ExaSearchProvider)


def test_NFR_03_builder_rejects_unknown_search_provider() -> None:
    plan = build_runtime_adapter_plan(
        {"DEMO_MODE": "0", "PROVIDER_SEARCH": "unknown"},
        fixture_root=FIXTURE_ROOT,
    )

    with pytest.raises(SearchConfigurationError, match="search_provider_not_allowlisted"):
        build_search_provider(plan)


def test_NFR_03_fixture_binding_comes_only_from_demo_catalog() -> None:
    plan = build_runtime_adapter_plan(
        {"DEMO_MODE": "1", "PROVIDER_SEARCH": "exa", "EXA_API_KEY": "ignored"},
        fixture_root=FIXTURE_ROOT,
    )
    provider = build_search_provider(plan)

    assert plan.bindings[AdapterCapability.SEARCH] == "fixture"
    assert isinstance(provider, FixtureSearchProvider)
