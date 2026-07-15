"""Typed, robots-aware public page retrieval over Mandate's SafeFetcher.

PageFetcher turns one public URL into bounded extracted text plus provenance. Returned
content remains untrusted and is explicitly not admitted as Evidence. Binary documents
remain unreachable until the malware-scan and sandbox parser boundary is available.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol, Self
from urllib.parse import urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup, Tag
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from mandate_worker.fetch import (
    SafeFetcher,
    SafeFetcherConfig,
    SafeFetchError,
    SafeFetchResult,
)
from mandate_worker.fetch.policy import SafeFetchPolicyError, canonicalize_url
from mandate_worker.fixtures import AdapterCapability, FixtureCatalog
from mandate_worker.runtime import RuntimeAdapterPlan

PAGE_FETCHER_VERSION: Literal["page-fetcher-v1"] = "page-fetcher-v1"
ROBOTS_USER_AGENT = "Mandate-SafeFetcher"
MAX_PAGE_BYTES = 2 * 1024 * 1024
MAX_ROBOTS_BYTES = 256 * 1024
MAX_EXTRACTED_CHARACTERS = 100_000
MAX_REDIRECTS_RECORDED = 5
MAX_CRAWL_DELAY_SECONDS = 5.0
HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
TEXT_CONTENT_TYPES = frozenset(
    {
        "application/xml",
        "text/plain",
        "text/xml",
    }
)
ACCESS_CONTROL_STATUSES = frozenset({401, 403, 407, 451})

PROMPT_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"ignore\s+(?:all\s+)?(?:previous|prior|system)\s+instructions",
        r"reveal\s+(?:the\s+)?system\s+prompt",
        r"you\s+are\s+(?:chatgpt|an?\s+ai|a\s+language\s+model)",
        r"exfiltrat(?:e|ion)\s+(?:secrets?|credentials?|tokens?)",
        r"do\s+not\s+follow\s+(?:the\s+)?(?:system|developer)\s+message",
    )
)
CAPTCHA_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"verify\s+(?:that\s+)?you\s+are\s+human",
        r"complete\s+the\s+captcha",
        r"g-recaptcha|hcaptcha|cf-turnstile",
    )
)
PAYWALL_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"subscribe\s+to\s+(?:continue|read|view)",
        r"sign\s+in\s+to\s+(?:continue|read|view)",
        r"this\s+content\s+is\s+(?:for\s+)?subscribers",
    )
)
AUTOMATION_RESTRICTION_PATTERNS = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        r"automated\s+(?:access|scraping|collection)\s+is\s+(?:strictly\s+)?prohibited",
        r"may\s+not\s+use\s+(?:robots?|bots?|spiders?|scrapers?)",
        r"no\s+(?:automated|machine)\s+(?:access|scraping|collection)",
    )
)


class PageRobotsStatus(StrEnum):
    ALLOWED = "allowed"
    ABSENT = "absent"
    FIXTURE = "fixture"


class PageFetchRequest(BaseModel):
    """Allowlisted public page request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1, max_length=2_048)

    @field_validator("url", mode="before")
    @classmethod
    def normalise_url(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("page URL must be a string")
        try:
            return canonicalize_url(value.strip())[0]
        except SafeFetchPolicyError as error:
            raise ValueError(error.code) from error


class PageDocument(BaseModel):
    """Bounded extracted page content that is still untrusted and unadmitted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_url: str = Field(min_length=1, max_length=2_048)
    final_url: str = Field(min_length=1, max_length=2_048)
    status_code: int = Field(ge=200, le=299)
    content_type: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    text: str = Field(min_length=1, max_length=MAX_EXTRACTED_CHARACTERS)
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    redirect_chain: tuple[str, ...] = Field(default=(), max_length=MAX_REDIRECTS_RECORDED)
    robots_status: PageRobotsStatus
    prompt_injection_suspected: bool
    extraction_version: Literal["page-fetcher-v1"] = PAGE_FETCHER_VERSION
    evidence_admitted: Literal[False] = False

    @model_validator(mode="after")
    def final_url_matches_redirect_chain(self) -> Self:
        if self.redirect_chain and self.redirect_chain[-1] != self.final_url:
            raise ValueError("final page URL must match the last redirect")
        return self


class PageFetchResponse(BaseModel):
    """Page fetch result with bounded provider-call metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request: PageFetchRequest
    provider: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_-]+$")
    fixture: bool
    provider_calls: int = Field(ge=0, le=2)
    document: PageDocument


class PageFetcher(Protocol):
    async def fetch(self, request: PageFetchRequest) -> PageFetchResponse:
        """Fetch one public page without admitting it as evidence."""


class PageFetcherConfigurationError(RuntimeError):
    """PageFetcher selection or fixture wiring is absent or unsafe."""


class PageFetcherError(RuntimeError):
    """Stable public-page failure with no body, URL or secret in the message."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class PageFetchClient(Protocol):
    async def fetch(self, url: str) -> SafeFetchResult:
        """Fetch through the ADR-011 SafeFetcher boundary."""


@dataclass(frozen=True, slots=True)
class _RobotsPolicy:
    status: PageRobotsStatus
    delay_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class SafePageFetcher:
    """Robots-aware live adapter over the DNS-pinned SafeFetcher."""

    fetcher: PageFetchClient
    sleeper: Callable[[float], Awaitable[None]] = field(
        default=asyncio.sleep,
        repr=False,
        compare=False,
    )

    async def fetch(self, request: PageFetchRequest) -> PageFetchResponse:
        robots = await self._load_robots(request.url)
        if robots.delay_seconds:
            await self.sleeper(robots.delay_seconds)
        try:
            result = await self.fetcher.fetch(request.url)
        except SafeFetchError as error:
            raise PageFetcherError(f"page_{error.code}", retryable=error.retryable) from error
        document = _document_from_safe_result(result, robots.status)
        return PageFetchResponse(
            request=request,
            provider="safe_fetcher",
            fixture=False,
            provider_calls=2,
            document=document,
        )

    async def _load_robots(self, page_url: str) -> _RobotsPolicy:
        robots_url = _robots_url(page_url)
        try:
            result = await self.fetcher.fetch(robots_url)
        except SafeFetchError as error:
            raise PageFetcherError(
                "page_robots_unavailable",
                retryable=error.retryable,
            ) from error

        page_host = urlsplit(page_url).hostname
        robots_host = urlsplit(result.final_url).hostname
        if page_host is None or robots_host != page_host:
            raise PageFetcherError("page_robots_offsite_redirect", retryable=False)
        if result.status_code in ACCESS_CONTROL_STATUSES:
            raise PageFetcherError("page_robots_denied", retryable=False)
        if result.status_code == 429 or result.status_code >= 500:
            raise PageFetcherError("page_robots_unavailable", retryable=True)
        if 400 <= result.status_code < 500:
            return _RobotsPolicy(PageRobotsStatus.ABSENT)
        if result.status_code < 200 or result.status_code >= 300:
            raise PageFetcherError("page_robots_http_error", retryable=False)
        if result.content_type not in {
            "application/xhtml+xml",
            "text/html",
            "text/plain",
        }:
            raise PageFetcherError("page_robots_content_type", retryable=False)
        if len(result.body) > MAX_ROBOTS_BYTES:
            raise PageFetcherError("page_robots_too_large", retryable=False)

        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(result.body.decode("utf-8", errors="replace").splitlines())
        if not parser.can_fetch(ROBOTS_USER_AGENT, page_url):
            raise PageFetcherError("page_robots_denied", retryable=False)
        delay = _robots_delay(parser)
        if delay > MAX_CRAWL_DELAY_SECONDS:
            raise PageFetcherError("page_robots_delay_exceeds_limit", retryable=False)
        return _RobotsPolicy(PageRobotsStatus.ALLOWED, delay)


class _FixtureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str = Field(min_length=1, max_length=2_048)


class _FixtureResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    content_type: str = Field(alias="contentType", min_length=1, max_length=100)
    status: int = Field(ge=200, le=299)
    body: str = Field(min_length=1, max_length=MAX_PAGE_BYTES)


class _PageFetcherFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    fixture_version: Literal[1] = Field(alias="fixtureVersion")
    request: _FixtureRequest
    response: _FixtureResponse


@dataclass(frozen=True, slots=True)
class FixturePageFetcher:
    """Deterministic, zero-network PageFetcher for demo mode."""

    fixture_request: PageFetchRequest
    fixture_status: int
    fixture_content_type: str
    fixture_body: bytes = field(repr=False)

    @classmethod
    def from_catalog(cls, catalog: FixtureCatalog) -> FixturePageFetcher:
        try:
            fixture = _PageFetcherFixture.model_validate(
                catalog.payload(AdapterCapability.PAGE_FETCHER)
            )
            request = PageFetchRequest(url=fixture.request.url)
            if fixture.response.content_type not in HTML_CONTENT_TYPES | TEXT_CONTENT_TYPES:
                raise ValueError("fixture page content type is not parseable")
            body = fixture.response.body.encode()
            if len(body) > MAX_PAGE_BYTES:
                raise ValueError("fixture page body exceeds the page limit")
        except (KeyError, ValidationError, ValueError) as error:
            raise PageFetcherConfigurationError("page_fetcher_fixture_invalid") from error
        return cls(
            fixture_request=request,
            fixture_status=fixture.response.status,
            fixture_content_type=fixture.response.content_type,
            fixture_body=body,
        )

    async def fetch(self, request: PageFetchRequest) -> PageFetchResponse:
        if request != self.fixture_request:
            raise PageFetcherError("page_fixture_not_found", retryable=False)
        title, text, prompt_injection_suspected = _extract_page_content(
            self.fixture_body,
            self.fixture_content_type,
        )
        document = PageDocument(
            requested_url=request.url,
            final_url=request.url,
            status_code=self.fixture_status,
            content_type=self.fixture_content_type,
            title=title,
            text=text,
            content_sha256=hashlib.sha256(self.fixture_body).hexdigest(),
            robots_status=PageRobotsStatus.FIXTURE,
            prompt_injection_suspected=prompt_injection_suspected,
        )
        return PageFetchResponse(
            request=request,
            provider="fixture",
            fixture=True,
            provider_calls=0,
            document=document,
        )


def build_page_fetcher(
    plan: RuntimeAdapterPlan,
    *,
    safe_fetcher: PageFetchClient | None = None,
) -> PageFetcher:
    """Build the selected PageFetcher without a credential-driven fallback."""

    binding = plan.bindings[AdapterCapability.PAGE_FETCHER]
    if binding == "fixture":
        if not plan.demo_mode or plan.catalog is None:
            raise PageFetcherConfigurationError("page_fetcher_fixture_requires_demo_mode")
        return FixturePageFetcher.from_catalog(plan.catalog)
    if binding == "safe_fetcher":
        if safe_fetcher is None:
            safe_fetcher = SafeFetcher(config=SafeFetcherConfig(max_response_bytes=MAX_PAGE_BYTES))
        return SafePageFetcher(safe_fetcher)
    if binding == "unconfigured":
        raise PageFetcherConfigurationError("page_fetcher_unconfigured")
    raise PageFetcherConfigurationError("page_fetcher_not_allowlisted")


def _document_from_safe_result(
    result: SafeFetchResult,
    robots_status: PageRobotsStatus,
) -> PageDocument:
    if result.status_code in ACCESS_CONTROL_STATUSES:
        raise PageFetcherError("page_access_denied", retryable=False)
    if result.status_code == 429:
        raise PageFetcherError("page_rate_limited", retryable=True)
    if result.status_code >= 500:
        raise PageFetcherError("page_unavailable", retryable=True)
    if result.status_code < 200 or result.status_code >= 300:
        raise PageFetcherError("page_http_error", retryable=False)
    if len(result.body) > MAX_PAGE_BYTES:
        raise PageFetcherError("page_response_too_large", retryable=False)
    if result.content_type == "application/pdf":
        raise PageFetcherError("page_binary_scan_required", retryable=False)
    if result.content_type not in HTML_CONTENT_TYPES | TEXT_CONTENT_TYPES:
        raise PageFetcherError("page_content_type_not_parseable", retryable=False)

    title, text, prompt_injection_suspected = _extract_page_content(
        result.body,
        result.content_type,
    )
    return PageDocument(
        requested_url=result.requested_url,
        final_url=result.final_url,
        status_code=result.status_code,
        content_type=result.content_type,
        title=title,
        text=text,
        content_sha256=hashlib.sha256(result.body).hexdigest(),
        redirect_chain=result.redirect_chain,
        robots_status=robots_status,
        prompt_injection_suspected=prompt_injection_suspected,
    )


def _extract_page_content(body: bytes, content_type: str) -> tuple[str, str, bool]:
    decoded = body.decode("utf-8", errors="replace")
    prompt_injection_suspected = any(
        pattern.search(decoded[:500_000]) for pattern in PROMPT_INJECTION_PATTERNS
    )
    if content_type in HTML_CONTENT_TYPES:
        title, visible_text = _extract_html(decoded)
    else:
        title = "Untitled page"
        visible_text = _normalise_text(decoded)

    search_surface = f"{decoded[:500_000]}\n{visible_text}"
    if any(pattern.search(search_surface) for pattern in CAPTCHA_PATTERNS):
        raise PageFetcherError("page_captcha_detected", retryable=False)
    if any(pattern.search(search_surface) for pattern in PAYWALL_PATTERNS):
        raise PageFetcherError("page_paywall_detected", retryable=False)
    if any(pattern.search(visible_text) for pattern in AUTOMATION_RESTRICTION_PATTERNS):
        raise PageFetcherError("page_automation_restricted", retryable=False)
    if not visible_text:
        raise PageFetcherError("page_content_empty", retryable=False)
    return title, visible_text[:MAX_EXTRACTED_CHARACTERS], prompt_injection_suspected


def _extract_html(decoded: str) -> tuple[str, str]:
    soup = BeautifulSoup(decoded, "html.parser")
    title_tag = soup.find("title")
    heading = soup.find("h1")
    raw_title = ""
    if isinstance(title_tag, Tag):
        raw_title = title_tag.get_text(" ", strip=True)
    elif isinstance(heading, Tag):
        raw_title = heading.get_text(" ", strip=True)
    title = " ".join(raw_title.split())[:500] or "Untitled page"

    for element in soup.find_all(("script", "style", "noscript", "template", "svg", "iframe")):
        element.decompose()
    for element in soup.find_all(True):
        if not isinstance(element, Tag) or element.parent is None or element.attrs is None:
            continue
        style = str(element.get("style", "")).replace(" ", "").casefold()
        if (
            element.has_attr("hidden")
            or str(element.get("aria-hidden", "")).casefold() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        ):
            element.decompose()
    return title, _normalise_text(soup.get_text("\n"))


def _normalise_text(value: str) -> str:
    lines = [" ".join(line.split()) for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _robots_url(page_url: str) -> str:
    parsed = urlsplit(page_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))


def _robots_delay(parser: RobotFileParser) -> float:
    delay = parser.crawl_delay(ROBOTS_USER_AGENT)
    if delay is None:
        delay = parser.crawl_delay("*")
    request_rate = parser.request_rate(ROBOTS_USER_AGENT) or parser.request_rate("*")
    rate_delay = 0.0
    if request_rate is not None and request_rate.requests > 0:
        rate_delay = request_rate.seconds / request_rate.requests
    return max(float(delay or 0), rate_delay)
