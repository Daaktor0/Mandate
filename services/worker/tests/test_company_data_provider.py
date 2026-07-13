from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import ClassVar, Self

import pytest
from mandate_worker.providers.company_data import (
    ATTESTR_MASTER_URL,
    ATTESTR_SEARCH_URL,
    AttestrCompanyDataProvider,
    AttestrHttpTransport,
    CompanyDataConfigurationError,
    CompanyDataHttpResponse,
    CompanyDataOperation,
    CompanyDataProviderError,
    CompanyDataTransportError,
    FixtureCompanyDataProvider,
    build_company_data_provider,
)
from mandate_worker.runtime import build_runtime_adapter_plan

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPOSITORY_ROOT / "fixtures" / "demo"
PRIVATE_CIN = "U62099MH2024PTC123456"
PUBLIC_CIN = "U64200DL2020PLC654321"


def json_response(payload: object, status_code: int = 200) -> CompanyDataHttpResponse:
    return CompanyDataHttpResponse(
        status_code=status_code,
        content_type="application/json; charset=utf-8",
        body=json.dumps(payload).encode(),
    )


@dataclass
class ScriptedTransport:
    responses: list[CompanyDataHttpResponse | CompanyDataTransportError]
    requests: list[tuple[CompanyDataOperation, Mapping[str, object]]] = field(default_factory=list)

    async def post_json(
        self,
        operation: CompanyDataOperation,
        payload: Mapping[str, object],
    ) -> CompanyDataHttpResponse:
        self.requests.append((operation, payload))
        response = self.responses.pop(0)
        if isinstance(response, CompanyDataTransportError):
            raise response
        return response


async def no_sleep(_: float) -> None:
    return None


@pytest.mark.asyncio
async def test_ENTITY_05_fixture_search_is_deterministic_and_zero_spend() -> None:
    plan = build_runtime_adapter_plan({"DEMO_MODE": "1"}, fixture_root=FIXTURE_ROOT)
    provider = build_company_data_provider(plan)
    assert isinstance(provider, FixtureCompanyDataProvider)

    result = await provider.search_by_name("  MANDATE   demo company  ")

    assert result.fixture is True
    assert result.provider_calls == 0
    assert [record.cin for record in result.records] == [PRIVATE_CIN, PUBLIC_CIN]
    assert result.records[0].legal_name == "MANDATE DEMO COMPANY PRIVATE LIMITED"
    assert result.records[0].registered_office_state == "Maharashtra"


@pytest.mark.asyncio
async def test_ENTITY_05_fixture_lookup_normalises_and_preserves_exact_cin() -> None:
    plan = build_runtime_adapter_plan({"DEMO_MODE": "1"}, fixture_root=FIXTURE_ROOT)
    provider = build_company_data_provider(plan)

    result = await provider.lookup_by_cin(PRIVATE_CIN.lower())

    assert result.public_query == PRIVATE_CIN
    assert len(result.records) == 1
    assert result.records[0].cin == PRIVATE_CIN
    assert result.records[0].former_names == ("MANDATE DEMO TECHNOLOGIES PRIVATE LIMITED",)


@pytest.mark.asyncio
async def test_ENTITY_05_invalid_cin_fails_before_any_provider_call() -> None:
    transport = ScriptedTransport([])
    provider = AttestrCompanyDataProvider(transport)

    with pytest.raises(ValueError, match="CIN is invalid"):
        await provider.lookup_by_cin("not-a-cin")

    assert transport.requests == []


@pytest.mark.asyncio
async def test_INTAKE_04_attestr_payload_is_a_public_data_allowlist() -> None:
    transport = ScriptedTransport([json_response([]), json_response({"valid": False})])
    provider = AttestrCompanyDataProvider(transport)

    await provider.search_by_name("Mandate Demo Company Private Limited", limit=7)
    await provider.lookup_by_cin(PRIVATE_CIN)

    search_operation, search_payload = transport.requests[0]
    lookup_operation, lookup_payload = transport.requests[1]
    assert search_operation is CompanyDataOperation.SEARCH_BY_NAME
    assert search_payload == {
        "businessName": {
            "matchCriteria": "EQUALS",
            "matchValue": "Mandate Demo Company Private Limited",
        },
        "skip": 0,
        "limit": 7,
        "sort": "score",
        "sortOrder": -1,
    }
    assert lookup_operation is CompanyDataOperation.LOOKUP_BY_CIN
    assert lookup_payload == {"reg": PRIVATE_CIN, "charges": False, "efilings": False}
    serialized = json.dumps([dict(search_payload), dict(lookup_payload)]).casefold()
    for forbidden in ("user", "firm", "billing", "letterhead", "email", "confidential"):
        assert forbidden not in serialized


@pytest.mark.asyncio
async def test_ENTITY_05_search_parses_only_bounded_company_fields() -> None:
    transport = ScriptedTransport(
        [
            json_response(
                [
                    {
                        "indexId": PRIVATE_CIN,
                        "businessName": "MANDATE DEMO COMPANY PRIVATE LIMITED",
                        "type": "Private Limited Company",
                        "status": "Active",
                        "active": True,
                        "incorporatedDate": "12-02-2024",
                        "addresses": [
                            {
                                "type": "Registered Address",
                                "state": "Maharashtra",
                                "fullAddress": "12 Synthetic Avenue, Mumbai",
                                "active": True,
                            }
                        ],
                        "directorsAndSignatories": [{"name": "must be discarded"}],
                        "email": "must-be-discarded@example.test",
                    }
                ]
            )
        ]
    )
    provider = AttestrCompanyDataProvider(transport)

    result = await provider.search_by_name("MANDATE DEMO COMPANY PRIVATE LIMITED")

    record = result.records[0]
    assert record.cin == PRIVATE_CIN
    assert record.incorporated_date is not None
    assert record.incorporated_date.isoformat() == "2024-02-12"
    assert record.registered_office_state == "Maharashtra"
    assert "email" not in record.model_dump()
    assert "directorsAndSignatories" not in record.model_dump()


@pytest.mark.asyncio
async def test_ENTITY_05_master_lookup_rejects_a_mismatched_cin() -> None:
    transport = ScriptedTransport(
        [
            json_response(
                {
                    "valid": True,
                    "reg": PUBLIC_CIN,
                    "businessName": "WRONG COMPANY LIMITED",
                }
            )
        ]
    )
    provider = AttestrCompanyDataProvider(transport)

    with pytest.raises(CompanyDataProviderError) as captured:
        await provider.lookup_by_cin(PRIVATE_CIN)

    assert captured.value.code == "company_data_response_invalid"
    assert captured.value.retryable is False
    assert captured.value.__suppress_context__ is True


@pytest.mark.asyncio
async def test_NFR_05_provider_calls_are_capped_and_auditable() -> None:
    transport = ScriptedTransport(
        [json_response({}, status_code=429), json_response([], status_code=200)]
    )
    provider = AttestrCompanyDataProvider(transport, sleeper=no_sleep)

    result = await provider.search_by_name("Mandate Demo Company")

    assert result.provider_calls == 2
    assert len(transport.requests) == 2


@pytest.mark.asyncio
async def test_NFR_05_call_cap_fails_after_second_retryable_error() -> None:
    transport = ScriptedTransport(
        [
            CompanyDataTransportError("company_data_transport_failed", retryable=True),
            json_response({}, status_code=503),
        ]
    )
    provider = AttestrCompanyDataProvider(transport, sleeper=no_sleep)

    with pytest.raises(CompanyDataProviderError) as captured:
        await provider.search_by_name("Mandate Demo Company")

    assert captured.value.code == "company_data_unavailable"
    assert captured.value.retryable is True
    assert len(transport.requests) == 2


@pytest.mark.asyncio
async def test_RUN_06_non_retryable_auth_failure_fails_safe_without_raw_body() -> None:
    transport = ScriptedTransport(
        [
            CompanyDataHttpResponse(
                status_code=401,
                content_type="application/json",
                body=b'{"message":"secret vendor detail"}',
            )
        ]
    )
    provider = AttestrCompanyDataProvider(transport)

    with pytest.raises(CompanyDataProviderError) as captured:
        await provider.search_by_name("Mandate Demo Company")

    assert str(captured.value) == "company_data_unauthorized"
    assert "secret vendor detail" not in repr(captured.value)
    assert captured.value.__suppress_context__ is True
    assert len(transport.requests) == 1


def test_NFR_03_live_provider_selection_never_silently_falls_back_to_fixture() -> None:
    unconfigured = build_runtime_adapter_plan({"DEMO_MODE": "0"})
    fixture_in_live = build_runtime_adapter_plan(
        {"DEMO_MODE": "0", "PROVIDER_COMPANY_DATA": "fixture"}
    )
    attestr_without_token = build_runtime_adapter_plan(
        {"DEMO_MODE": "0", "PROVIDER_COMPANY_DATA": "attestr"}
    )

    with pytest.raises(CompanyDataConfigurationError, match="company_data_provider_unconfigured"):
        build_company_data_provider(unconfigured, {})
    with pytest.raises(
        CompanyDataConfigurationError, match="company_data_fixture_requires_demo_mode"
    ):
        build_company_data_provider(fixture_in_live, {})
    with pytest.raises(CompanyDataConfigurationError, match="company_data_credentials_missing"):
        build_company_data_provider(attestr_without_token, {})


@pytest.mark.asyncio
async def test_INTAKE_04_attestr_http_transport_is_fixed_no_proxy_and_no_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_options: dict[str, object] = {}
    stream_options: dict[str, object] = {}

    class CapturingResponse:
        status_code = 200
        headers: ClassVar[dict[str, str]] = {"content-type": "application/json"}

        async def aiter_raw(self) -> AsyncIterator[bytes]:
            yield b"[]"

    class CapturingResponseContext:
        async def __aenter__(self) -> CapturingResponse:
            return CapturingResponse()

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    class CapturingClient:
        def __init__(self, **options: object) -> None:
            client_options.update(options)

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

        def stream(self, method: str, url: str, **options: object) -> CapturingResponseContext:
            stream_options.update({"method": method, "url": url, **options})
            return CapturingResponseContext()

    monkeypatch.setattr("mandate_worker.providers.company_data.httpx.AsyncClient", CapturingClient)
    transport = AttestrHttpTransport("private-auth-token")

    response = await transport.post_json(
        CompanyDataOperation.SEARCH_BY_NAME,
        {"businessName": {"matchCriteria": "EQUALS", "matchValue": "Public Co"}},
    )

    assert response.body == b"[]"
    assert client_options["follow_redirects"] is False
    assert client_options["trust_env"] is False
    assert stream_options["method"] == "POST"
    assert stream_options["url"] == ATTESTR_SEARCH_URL
    headers = stream_options["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Basic private-auth-token"
    assert headers["Accept-Encoding"] == "identity"
    assert "private-auth-token" not in repr(transport)
    assert ATTESTR_MASTER_URL.startswith("https://api.attestr.com/")
