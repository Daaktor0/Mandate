"""Typed, bounded public-web search provider boundary.

Search is discovery only. Returned URLs remain untrusted and must pass through
Mandate's SafeFetcher before page content becomes evidence. The provider request
cannot carry user identity, firm, billing, letterhead, or matter-document fields.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final, Protocol, Self
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from mandate_worker.fixtures import AdapterCapability, FixtureCatalog
from mandate_worker.runtime import RuntimeAdapterPlan

EXA_SEARCH_URL: Final = "https://api.exa.ai/search"
MAX_QUERY_LENGTH: Final = 500
MAX_RESULTS: Final = 20
MAX_DOMAINS: Final = 20
MAX_HIGHLIGHTS: Final = 5
MAX_HIGHLIGHT_LENGTH: Final = 2_000
MAX_PROVIDER_CALLS: Final = 2
MAX_RESPONSE_BYTES: Final = 2_097_152
MAX_COST_USD: Final = 100.0


class SearchRequest(BaseModel):
    """Allowlisted public-web search request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)
    limit: int = Field(default=10, ge=1, le=MAX_RESULTS)
    include_domains: tuple[str, ...] = Field(default=(), max_length=MAX_DOMAINS)
    exclude_domains: tuple[str, ...] = Field(default=(), max_length=MAX_DOMAINS)
    start_published_at: datetime | None = None
    end_published_at: datetime | None = None

    @field_validator("query", mode="before")
    @classmethod
    def normalise_query(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("search query must be a string")
        query = " ".join(value.split())
        if not query or len(query) > MAX_QUERY_LENGTH:
            raise ValueError("search query is empty or exceeds the provider limit")
        if any(ord(character) < 32 or ord(character) == 127 for character in query):
            raise ValueError("search query contains control characters")
        return query

    @field_validator("include_domains", "exclude_domains", mode="before")
    @classmethod
    def normalise_domains(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, list | tuple):
            raise ValueError("search domains must be a sequence")
        domains = tuple(_normalise_domain(item) for item in value)
        if len(domains) != len(set(domains)):
            raise ValueError("search domains must be unique")
        return domains

    @field_validator("start_published_at", "end_published_at")
    @classmethod
    def published_dates_must_be_timezone_aware(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("published-date filters must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_filter_relationships(self) -> Self:
        if set(self.include_domains) & set(self.exclude_domains):
            raise ValueError("a search domain cannot be both included and excluded")
        if (
            self.start_published_at is not None
            and self.end_published_at is not None
            and self.start_published_at > self.end_published_at
        ):
            raise ValueError("published-date range is reversed")
        return self


class SearchResult(BaseModel):
    """Bounded discovery result; not yet fetched or accepted as evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2_048)
    source_id: str = Field(min_length=1, max_length=2_048)
    published_at: datetime | None = None
    author: str | None = Field(default=None, max_length=500)
    highlights: tuple[str, ...] = Field(default=(), max_length=MAX_HIGHLIGHTS)

    @field_validator("title", mode="before")
    @classmethod
    def normalise_title(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("search result title must be a string")
        title = " ".join(value.split())
        if not title:
            raise ValueError("search result title is empty")
        return title[:500]

    @field_validator("url", mode="before")
    @classmethod
    def normalise_url(cls, value: object) -> str:
        return _normalise_public_url(value)

    @field_validator("source_id", mode="before")
    @classmethod
    def normalise_source_id(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("search result source id must be a string")
        source_id = " ".join(value.split())
        if not source_id:
            raise ValueError("search result source id is empty")
        return source_id[:2_048]

    @field_validator("published_at")
    @classmethod
    def published_at_must_be_timezone_aware(
        cls, value: datetime | None
    ) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("search result published date must be timezone-aware")
        return value

    @field_validator("author", mode="before")
    @classmethod
    def normalise_author(cls, value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("search result author must be a string")
        author = " ".join(value.split())
        return author[:500] or None

    @field_validator("highlights", mode="before")
    @classmethod
    def normalise_highlights(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            raw_values = (value,)
        elif isinstance(value, list | tuple):
            raw_values = tuple(value)
        else:
            raise ValueError("search result highlights must be a sequence")
        highlights: list[str] = []
        for raw in raw_values[:MAX_HIGHLIGHTS]:
            if not isinstance(raw, str):
                raise ValueError("search result highlight must be a string")
            highlight = " ".join(raw.split())[:MAX_HIGHLIGHT_LENGTH]
            if highlight and highlight not in highlights:
                highlights.append(highlight)
        return tuple(highlights)


class SearchResponse(BaseModel):
    """Bounded search response with audit and cost metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: SearchRequest
    provider: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_-]+$")
    fixture: bool
    provider_calls: int = Field(ge=0, le=MAX_PROVIDER_CALLS)
    cost_usd: float = Field(default=0.0, ge=0, le=MAX_COST_USD)
    results: tuple[SearchResult, ...] = Field(max_length=MAX_RESULTS)


class SearchProvider(Protocol):
    async def search(self, request: SearchRequest) -> SearchResponse:
        """Discover public URLs without accepting their contents as evidence."""


class SearchConfigurationError(RuntimeError):
    """Search-provider selection or credentials are absent or unsafe."""


class SearchProviderError(RuntimeError):
    """Stable provider failure that never contains a response body or secret."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class SearchTransportError(RuntimeError):
    """Sanitised transport failure."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class SearchHttpResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status_code: int = Field(ge=100, le=599)
    content_type: str | None = Field(default=None, max_length=200)
    body: bytes = Field(max_length=MAX_RESPONSE_BYTES)


class ExaTransport(Protocol):
    async def post_json(self, payload: Mapping[str, object]) -> SearchHttpResponse:
        """POST an allowlisted payload to Exa's fixed search endpoint."""


@dataclass(frozen=True, slots=True)
class ExaHttpTransport:
    """No-proxy, no-redirect transport restricted to Exa's search endpoint."""

    api_key: str = field(repr=False)
    timeout_seconds: float = 10.0
    max_response_bytes: int = MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise SearchConfigurationError("search_credentials_missing")
        if not 0 < self.timeout_seconds <= 20:
            raise SearchConfigurationError("search_timeout_invalid")
        if not 1 <= self.max_response_bytes <= MAX_RESPONSE_BYTES:
            raise SearchConfigurationError("search_response_cap_invalid")

    async def post_json(self, payload: Mapping[str, object]) -> SearchHttpResponse:
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Content-Type": "application/json",
            "User-Agent": "Mandate-SearchProvider/1.0",
            "x-api-key": self.api_key,
        }
        timeout = httpx.Timeout(self.timeout_seconds)
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                trust_env=False,
                timeout=timeout,
            ) as client:
                async with client.stream(
                    "POST",
                    EXA_SEARCH_URL,
                    headers=headers,
                    json=dict(payload),
                ) as response:
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        body.extend(chunk)
                        if len(body) > self.max_response_bytes:
                            raise SearchTransportError(
                                "search_response_too_large", retryable=False
                            )
                    return SearchHttpResponse(
                        status_code=response.status_code,
                        content_type=response.headers.get("content-type"),
                        body=bytes(body),
                    )
        except SearchTransportError:
            raise
        except httpx.TransportError as error:
            raise SearchTransportError("search_transport_failed", retryable=True) from error


class _FixtureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str = Field(min_length=1, max_length=MAX_QUERY_LENGTH)


class _FixtureResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    title: str = Field(min_length=1, max_length=500)
    url: str = Field(min_length=1, max_length=2_048)
    snippet: str = Field(min_length=1, max_length=MAX_HIGHLIGHT_LENGTH)


class _FixtureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    results: tuple[_FixtureResult, ...] = Field(max_length=MAX_RESULTS)


class _SearchFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    fixture_version: int = Field(alias="fixtureVersion")
    request: _FixtureRequest
    response: _FixtureResponse


@dataclass(frozen=True, slots=True)
class FixtureSearchProvider:
    """Deterministic, zero-spend search implementation for demo mode."""

    fixture_query: str
    fixture_results: tuple[SearchResult, ...]

    @classmethod
    def from_catalog(cls, catalog: FixtureCatalog) -> FixtureSearchProvider:
        try:
            fixture = _SearchFixture.model_validate(catalog.payload(AdapterCapability.SEARCH))
            if fixture.fixture_version != 1:
                raise ValueError("unsupported search fixture version")
            results = tuple(
                SearchResult(
                    title=item.title,
                    url=item.url,
                    source_id=item.url,
                    highlights=(item.snippet,),
                )
                for item in fixture.response.results
            )
        except (KeyError, ValidationError, ValueError) as error:
            raise SearchConfigurationError("search_fixture_invalid") from error
        return cls(fixture_query=fixture.request.query, fixture_results=results)

    async def search(self, request: SearchRequest) -> SearchResponse:
        results = self.fixture_results[: request.limit] if request.query == self.fixture_query else ()
        return SearchResponse(
            request=request,
            provider="fixture",
            fixture=True,
            provider_calls=0,
            results=results,
        )


class _ExaResult(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    title: str = Field(min_length=1, max_length=2_000)
    url: str = Field(min_length=1, max_length=4_096)
    result_id: str | None = Field(default=None, alias="id", max_length=4_096)
    published_at: datetime | None = Field(default=None, alias="publishedDate")
    author: str | None = Field(default=None, max_length=2_000)
    highlights: tuple[str, ...] = Field(default=(), max_length=50)


class _ExaCost(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    total: float = Field(default=0.0, ge=0, le=MAX_COST_USD)


class _ExaResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)

    results: tuple[_ExaResult, ...] = Field(max_length=100)
    cost_dollars: _ExaCost | None = Field(default=None, alias="costDollars")


@dataclass(frozen=True, slots=True)
class ExaSearchProvider:
    """Extractive-highlight search adapter for Exa's current public API."""

    transport: ExaTransport
    retry_delay: Callable[[float], Awaitable[None]] = field(
        default=asyncio.sleep, repr=False, compare=False
    )

    async def search(self, request: SearchRequest) -> SearchResponse:
        payload = _exa_payload(request)
        provider_calls = 0
        for attempt in range(MAX_PROVIDER_CALLS):
            provider_calls += 1
            try:
                response = await self.transport.post_json(payload)
            except SearchTransportError as error:
                if not error.retryable or attempt + 1 >= MAX_PROVIDER_CALLS:
                    raise SearchProviderError(error.code, retryable=error.retryable) from error
                await self.retry_delay(0.05)
                continue

            failure = _classify_http_failure(response)
            if failure is not None:
                if not failure.retryable or attempt + 1 >= MAX_PROVIDER_CALLS:
                    raise failure
                await self.retry_delay(0.05)
                continue

            parsed = _parse_exa_response(response.body, request.limit)
            return SearchResponse(
                request=request,
                provider="exa",
                fixture=False,
                provider_calls=provider_calls,
                cost_usd=parsed[1],
                results=parsed[0],
            )
        raise SearchProviderError("search_unavailable", retryable=True)


def build_search_provider(
    plan: RuntimeAdapterPlan,
    *,
    environ: Mapping[str, str] | None = None,
    exa_transport: ExaTransport | None = None,
) -> SearchProvider:
    """Build the selected provider without credential-driven fallback."""

    binding = plan.bindings[AdapterCapability.SEARCH]
    if binding == "fixture":
        if not plan.demo_mode or plan.catalog is None:
            raise SearchConfigurationError("search_fixture_requires_demo_mode")
        return FixtureSearchProvider.from_catalog(plan.catalog)
    if binding == "exa":
        environment = os.environ if environ is None else environ
        api_key = environment.get("EXA_API_KEY", "").strip()
        if exa_transport is None:
            if not api_key:
                raise SearchConfigurationError("search_credentials_missing")
            exa_transport = ExaHttpTransport(api_key)
        return ExaSearchProvider(exa_transport)
    if binding == "unconfigured":
        raise SearchConfigurationError("search_provider_unconfigured")
    raise SearchConfigurationError("search_provider_not_allowlisted")


def _exa_payload(request: SearchRequest) -> Mapping[str, object]:
    payload: dict[str, object] = {
        "query": request.query,
        "type": "auto",
        "numResults": request.limit,
        "moderation": True,
        "contents": {
            "highlights": {
                "query": request.query,
                "maxCharacters": MAX_HIGHLIGHT_LENGTH,
            }
        },
    }
    if request.include_domains:
        payload["includeDomains"] = list(request.include_domains)
    if request.exclude_domains:
        payload["excludeDomains"] = list(request.exclude_domains)
    if request.start_published_at is not None:
        payload["startPublishedDate"] = request.start_published_at.isoformat()
    if request.end_published_at is not None:
        payload["endPublishedDate"] = request.end_published_at.isoformat()
    return payload


def _parse_exa_response(body: bytes, limit: int) -> tuple[tuple[SearchResult, ...], float]:
    try:
        raw = json.loads(body)
        parsed = _ExaResponse.model_validate(raw)
        results: list[SearchResult] = []
        seen_urls: set[str] = set()
        for item in parsed.results:
            result = SearchResult(
                title=item.title,
                url=item.url,
                source_id=item.result_id or item.url,
                published_at=item.published_at,
                author=item.author,
                highlights=item.highlights,
            )
            if result.url in seen_urls:
                continue
            seen_urls.add(result.url)
            results.append(result)
            if len(results) >= limit:
                break
    except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as error:
        raise SearchProviderError("search_response_invalid", retryable=False) from error
    cost = parsed.cost_dollars.total if parsed.cost_dollars is not None else 0.0
    return tuple(results), cost


def _classify_http_failure(response: SearchHttpResponse) -> SearchProviderError | None:
    if response.status_code == 200:
        media_type = (response.content_type or "").partition(";")[0].strip().lower()
        if media_type != "application/json":
            return SearchProviderError("search_response_invalid", retryable=False)
        return None
    if response.status_code == 400:
        return SearchProviderError("search_invalid_request", retryable=False)
    if response.status_code in {401, 403}:
        return SearchProviderError("search_unauthorized", retryable=False)
    if response.status_code == 429:
        return SearchProviderError("search_rate_limited", retryable=True)
    if 500 <= response.status_code <= 599:
        return SearchProviderError("search_unavailable", retryable=True)
    return SearchProviderError("search_http_error", retryable=False)


def _normalise_domain(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("search domain must be a string")
    domain = value.strip().rstrip(".").casefold()
    if (
        not domain
        or len(domain) > 253
        or "://" in domain
        or "/" in domain
        or "@" in domain
        or ":" in domain
        or any(ord(character) < 33 or ord(character) == 127 for character in domain)
    ):
        raise ValueError("search domain is invalid")
    labels = domain.split(".")
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not all(character.isalnum() or character == "-" for character in label)
        for label in labels
    ):
        raise ValueError("search domain is invalid")
    return domain


def _normalise_public_url(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("search result URL must be a string")
    split = urlsplit(value.strip())
    if split.scheme.casefold() not in {"http", "https"} or not split.hostname:
        raise ValueError("search result URL must use HTTP or HTTPS")
    if split.username is not None or split.password is not None:
        raise ValueError("search result URL cannot contain credentials")
    try:
        port = split.port
    except ValueError as error:
        raise ValueError("search result URL port is invalid") from error
    if port is not None and port != (80 if split.scheme.casefold() == "http" else 443):
        raise ValueError("search result URL must use the default port")
    hostname = split.hostname.casefold().rstrip(".")
    netloc = hostname
    if port is not None:
        netloc = f"{hostname}:{port}"
    return urlunsplit(
        (
            split.scheme.casefold(),
            netloc,
            split.path or "/",
            split.query,
            "",
        )
    )
