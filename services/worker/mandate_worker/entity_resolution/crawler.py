"""Bounded, policy-respecting inspection of company-controlled legal pages."""

from __future__ import annotations

import asyncio
import hashlib
import heapq
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from mandate_worker.fetch import SafeFetchError, SafeFetchResult
from mandate_worker.fetch.policy import SafeFetchPolicyError, canonicalize_url

from .extraction import EXTRACTION_VERSION, DiscoveredLink, extract_legal_page
from .models import (
    CrawlLimitation,
    LimitationCode,
    PageInspection,
    PageKind,
    RobotsStatus,
    SiteInspection,
)

CRAWLER_POLICY_VERSION = "legal-site-crawler-v1"
ROBOTS_USER_AGENT = "Mandate-SafeFetcher"
TRACKING_QUERY_KEYS = frozenset({"fbclid", "gclid", "mc_cid", "mc_eid"})
HTML_CONTENT_TYPES = frozenset({"text/html", "application/xhtml+xml"})
PDF_CONTENT_TYPE = "application/pdf"

ACCESS_CONTROL_STATUSES = frozenset({401, 403, 407, 451})
STOP_DOMAIN_STATUSES = frozenset({429})


class FetchClient(Protocol):
    async def fetch(self, url: str) -> SafeFetchResult:
        """Fetch through the ADR-011 SafeFetcher boundary."""


@dataclass(frozen=True, slots=True)
class CrawlerConfig:
    max_pages: int = 15
    max_candidates: int = 100
    max_html_bytes: int = 2 * 1024 * 1024
    max_robots_bytes: int = 256 * 1024
    max_crawl_delay_seconds: float = 5.0

    def __post_init__(self) -> None:
        if not 1 <= self.max_pages <= 15:
            raise ValueError("max_pages must be between 1 and 15")
        if not 1 <= self.max_candidates <= 100:
            raise ValueError("max_candidates must be between 1 and 100")
        if not 1 <= self.max_html_bytes <= 2 * 1024 * 1024:
            raise ValueError("max_html_bytes must be between 1 and 2 MiB")
        if not 1 <= self.max_robots_bytes <= 256 * 1024:
            raise ValueError("max_robots_bytes must be between 1 and 256 KiB")
        if not 0 <= self.max_crawl_delay_seconds <= 5:
            raise ValueError("max_crawl_delay_seconds must be between 0 and 5")


@dataclass(frozen=True, slots=True)
class _RobotsPolicy:
    status: RobotsStatus
    parser: RobotFileParser | None
    delay_seconds: float

    def allows(self, url: str) -> bool:
        if self.status in {RobotsStatus.DENIED, RobotsStatus.UNAVAILABLE}:
            return False
        return self.parser is None or self.parser.can_fetch(ROBOTS_USER_AGENT, url)


@dataclass(frozen=True, slots=True, order=True)
class _Candidate:
    priority: int
    discovered_order: int
    url: str
    page_kind: PageKind


LINK_RULES: tuple[tuple[PageKind, tuple[re.Pattern[str], ...]], ...] = (
    (PageKind.CONTACT, (re.compile(r"\bcontact(?:-us)?\b", re.I),)),
    (PageKind.PRIVACY, (re.compile(r"\bprivacy\b", re.I),)),
    (
        PageKind.CONSUMER_TERMS,
        (
            re.compile(r"\bconsumer\b.*\bterms?\b", re.I),
            re.compile(r"\bterms?\b.*\bconsumer\b", re.I),
        ),
    ),
    (PageKind.COOKIE_POLICY, (re.compile(r"\bcookies?\b", re.I),)),
    (
        PageKind.ANNUAL_REPORT,
        (
            re.compile(r"\bannual[-_ ]?reports?\b", re.I),
            re.compile(r"\bfinancial[-_ ]?(?:reports?|statements?)\b", re.I),
            re.compile(r"\bpolic(?:y|ies)\b", re.I),
        ),
    ),
    (
        PageKind.LEGAL_NOTICE,
        (
            re.compile(r"\blegal[-_ ]?(?:notice|information|disclosure)\b", re.I),
            re.compile(r"\bimprint\b", re.I),
        ),
    ),
    (
        PageKind.INVESTOR_RELATIONS,
        (
            re.compile(r"\binvestors?\b", re.I),
            re.compile(r"\binvestor[-_ ]?relations?\b", re.I),
        ),
    ),
    (PageKind.GOVERNANCE, (re.compile(r"\b(?:corporate[-_ ]?)?governance\b", re.I),)),
    (PageKind.CAREERS, (re.compile(r"\b(?:careers?|jobs?|work[-_ ]?with[-_ ]?us)\b", re.I),)),
    (
        PageKind.CORPORATE_DISCLOSURE,
        (
            re.compile(
                r"\b(?:corporate|company)[-_ ]?(?:information|profile|disclosures?)\b", re.I
            ),
            re.compile(r"\b(?:cin|gstin|registered[-_ ]?office)\b", re.I),
            re.compile(r"\babout[-_ ]?us\b", re.I),
        ),
    ),
    (
        PageKind.TERMS,
        (
            re.compile(r"\bterms?(?:[-_ ]?(?:and|&)[-_ ]?conditions?)?\b", re.I),
            re.compile(r"\bconditions[-_ ]?of[-_ ]?use\b", re.I),
        ),
    ),
)

PAGE_PRIORITIES = {
    PageKind.HOME: 0,
    PageKind.CONTACT: 10,
    PageKind.PRIVACY: 20,
    PageKind.TERMS: 30,
    PageKind.LEGAL_NOTICE: 40,
    PageKind.COOKIE_POLICY: 50,
    PageKind.INVESTOR_RELATIONS: 60,
    PageKind.GOVERNANCE: 70,
    PageKind.ANNUAL_REPORT: 80,
    PageKind.CAREERS: 90,
    PageKind.CONSUMER_TERMS: 100,
    PageKind.CORPORATE_DISCLOSURE: 110,
}


def _limitation(code: LimitationCode, detail_code: str, url: str | None = None) -> CrawlLimitation:
    return CrawlLimitation(code=code, url=url, detail_code=detail_code)


def _robots_url(start_url: str) -> str:
    parsed = urlsplit(start_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))


def _scope_host(hostname: str) -> str:
    return hostname[4:] if hostname.startswith("www.") else hostname


def _same_site(url: str, scope_host: str) -> bool:
    hostname = urlsplit(url).hostname
    if hostname is None:
        return False
    hostname = hostname.rstrip(".").lower()
    return hostname in {scope_host, f"www.{scope_host}"}


def _canonical_candidate(url: str) -> str:
    canonical, scheme, hostname, _port, path_query = canonicalize_url(url)
    parsed = urlsplit(canonical)
    retained_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in TRACKING_QUERY_KEYS and not key.casefold().startswith("utm_")
    ]
    path = path_query.split("?", maxsplit=1)[0]
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    return urlunsplit((scheme, netloc, path, urlencode(retained_query, doseq=True), ""))


def _classify_link(link: DiscoveredLink) -> PageKind | None:
    parsed = urlsplit(link.url)
    search_surface = f"{parsed.path} {parsed.query} {link.label}".replace("/", " ")
    for page_kind, patterns in LINK_RULES:
        if any(pattern.search(search_surface) for pattern in patterns):
            return page_kind
    return None


def _is_pdf_candidate(url: str) -> bool:
    return urlsplit(url).path.casefold().endswith(".pdf")


def _robots_delay(parser: RobotFileParser) -> float:
    delay = parser.crawl_delay(ROBOTS_USER_AGENT)
    if delay is None:
        delay = parser.crawl_delay("*")
    request_rate = parser.request_rate(ROBOTS_USER_AGENT) or parser.request_rate("*")
    rate_delay = 0.0
    if request_rate is not None and request_rate.requests > 0:
        rate_delay = request_rate.seconds / request_rate.requests
    return max(float(delay or 0), rate_delay)


class LegalPageCrawler:
    """Inspect legal pages deterministically without bypassing site or network policy."""

    def __init__(
        self,
        fetcher: FetchClient,
        *,
        config: CrawlerConfig | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._fetcher = fetcher
        self._config = config or CrawlerConfig()
        self._sleeper = sleeper

    async def _load_robots(
        self,
        root_url: str,
        scope_host: str,
        limitations: list[CrawlLimitation],
    ) -> _RobotsPolicy:
        url = _robots_url(root_url)
        try:
            result = await self._fetcher.fetch(url)
        except SafeFetchError as error:
            limitations.append(_limitation(LimitationCode.ROBOTS_UNAVAILABLE, error.code, url))
            return _RobotsPolicy(RobotsStatus.UNAVAILABLE, None, 0)

        if not _same_site(result.final_url, scope_host):
            limitations.append(
                _limitation(LimitationCode.ROBOTS_UNAVAILABLE, "robots_offsite_redirect", url)
            )
            return _RobotsPolicy(RobotsStatus.UNAVAILABLE, None, 0)

        if result.status_code in ACCESS_CONTROL_STATUSES:
            limitations.append(_limitation(LimitationCode.ROBOTS_DENIED, "http_denied", url))
            return _RobotsPolicy(RobotsStatus.DENIED, None, 0)
        if result.status_code in STOP_DOMAIN_STATUSES or result.status_code >= 500:
            limitations.append(
                _limitation(LimitationCode.ROBOTS_UNAVAILABLE, "http_unavailable", url)
            )
            return _RobotsPolicy(RobotsStatus.UNAVAILABLE, None, 0)
        if 400 <= result.status_code < 500:
            return _RobotsPolicy(RobotsStatus.ABSENT, None, 0)
        if result.content_type not in {"text/plain", "text/html", "application/xhtml+xml"}:
            limitations.append(
                _limitation(LimitationCode.ROBOTS_UNAVAILABLE, "robots_content_type", url)
            )
            return _RobotsPolicy(RobotsStatus.UNAVAILABLE, None, 0)
        if len(result.body) > self._config.max_robots_bytes:
            limitations.append(
                _limitation(LimitationCode.ROBOTS_UNAVAILABLE, "robots_too_large", url)
            )
            return _RobotsPolicy(RobotsStatus.UNAVAILABLE, None, 0)

        parser = RobotFileParser()
        parser.set_url(url)
        parser.parse(result.body.decode("utf-8", errors="replace").splitlines())
        delay = _robots_delay(parser)
        if delay > self._config.max_crawl_delay_seconds:
            limitations.append(
                _limitation(
                    LimitationCode.CRAWL_DELAY_EXCEEDS_BUDGET,
                    "crawl_delay_above_cap",
                    url,
                )
            )
            return _RobotsPolicy(RobotsStatus.DENIED, parser, delay)
        return _RobotsPolicy(RobotsStatus.ALLOWED, parser, delay)

    async def inspect(self, start_url: str) -> SiteInspection:
        try:
            root_url = _canonical_candidate(start_url)
        except SafeFetchPolicyError as error:
            raise SafeFetchError(error.code) from error
        hostname = urlsplit(root_url).hostname
        if hostname is None:  # pragma: no cover - canonical URL invariant
            raise SafeFetchError("invalid_hostname")
        scope_host = _scope_host(hostname)
        limitations: list[CrawlLimitation] = []
        robots = await self._load_robots(root_url, scope_host, limitations)
        if robots.status in {RobotsStatus.DENIED, RobotsStatus.UNAVAILABLE}:
            return SiteInspection(
                root_url=root_url,
                robots_status=robots.status,
                pages=(),
                limitations=tuple(limitations),
                discovered_document_urls=(),
                page_fetch_attempts=0,
                policy_version=CRAWLER_POLICY_VERSION,
            )

        queue: list[_Candidate] = [_Candidate(0, 0, root_url, PageKind.HOME)]
        best_priority = {root_url: 0}
        visited: set[str] = set()
        final_seen: set[str] = set()
        pages: list[PageInspection] = []
        documents: list[str] = []
        document_set: set[str] = set()
        discovered_order = 0
        fetch_attempts = 0
        stop_domain = False

        while queue and fetch_attempts < self._config.max_pages and not stop_domain:
            candidate = heapq.heappop(queue)
            if candidate.url in visited or best_priority.get(candidate.url) != candidate.priority:
                continue
            visited.add(candidate.url)
            if not robots.allows(candidate.url):
                limitations.append(
                    _limitation(LimitationCode.ROBOTS_DENIED, "path_disallowed", candidate.url)
                )
                continue
            if robots.delay_seconds > 0 and fetch_attempts > 0:
                await self._sleeper(robots.delay_seconds)

            fetch_attempts += 1
            try:
                result = await self._fetcher.fetch(candidate.url)
            except SafeFetchError as error:
                limitations.append(
                    _limitation(LimitationCode.FETCH_FAILED, error.code, candidate.url)
                )
                continue

            if not _same_site(result.final_url, scope_host):
                limitations.append(
                    _limitation(
                        LimitationCode.OFFSITE_REDIRECT, "redirect_left_site", candidate.url
                    )
                )
                continue
            if result.final_url in final_seen:
                continue
            final_seen.add(result.final_url)
            visited.add(result.final_url)
            if result.status_code in ACCESS_CONTROL_STATUSES:
                limitations.append(
                    _limitation(LimitationCode.ACCESS_CONTROLLED, "http_denied", candidate.url)
                )
                continue
            if result.status_code in STOP_DOMAIN_STATUSES:
                limitations.append(
                    _limitation(LimitationCode.ACCESS_CONTROLLED, "rate_limited", candidate.url)
                )
                stop_domain = True
                continue
            if not 200 <= result.status_code < 300:
                limitations.append(
                    _limitation(
                        LimitationCode.HTTP_STATUS,
                        f"http_{result.status_code}",
                        candidate.url,
                    )
                )
                continue
            if result.content_type == PDF_CONTENT_TYPE:
                if result.final_url not in document_set:
                    document_set.add(result.final_url)
                    documents.append(result.final_url)
                limitations.append(
                    _limitation(
                        LimitationCode.UNSUPPORTED_DOCUMENT,
                        "pdf_sandbox_pending",
                        result.final_url,
                    )
                )
                continue
            if result.content_type not in HTML_CONTENT_TYPES:
                limitations.append(
                    _limitation(
                        LimitationCode.UNSUPPORTED_DOCUMENT,
                        "non_html_document",
                        result.final_url,
                    )
                )
                continue
            if len(result.body) > self._config.max_html_bytes:
                limitations.append(
                    _limitation(LimitationCode.PAGE_TOO_LARGE, "html_above_cap", result.final_url)
                )
                continue

            extracted = extract_legal_page(result.body, result.final_url)
            if extracted.captcha_detected:
                limitations.append(
                    _limitation(
                        LimitationCode.CAPTCHA_DETECTED,
                        "captcha_not_bypassed",
                        result.final_url,
                    )
                )
                continue
            if extracted.paywall_detected:
                limitations.append(
                    _limitation(
                        LimitationCode.PAYWALL_DETECTED,
                        "paywall_not_bypassed",
                        result.final_url,
                    )
                )
                continue

            pages.append(
                PageInspection(
                    requested_url=candidate.url,
                    canonical_url=result.final_url,
                    page_kind=candidate.page_kind,
                    status_code=result.status_code,
                    title=extracted.title,
                    publisher=scope_host,
                    content_type=result.content_type,
                    content_hash=hashlib.sha256(result.body).hexdigest(),
                    excerpt=extracted.excerpt,
                    disclosures=extracted.disclosures,
                    prompt_injection_suspected=extracted.prompt_injection_suspected,
                    company_controlled=True,
                    extraction_version=EXTRACTION_VERSION,
                )
            )
            if extracted.automation_restricted:
                limitations.append(
                    _limitation(
                        LimitationCode.TERMS_RESTRICT_AUTOMATION,
                        "terms_prohibit_automation",
                        result.final_url,
                    )
                )
                stop_domain = True
                continue

            for link in extracted.links:
                page_kind = _classify_link(link)
                if page_kind is None:
                    continue
                try:
                    url = _canonical_candidate(link.url)
                except SafeFetchPolicyError:
                    continue
                if not _same_site(url, scope_host):
                    continue
                if _is_pdf_candidate(url):
                    if url not in document_set and len(documents) < 100:
                        document_set.add(url)
                        documents.append(url)
                    continue
                priority = PAGE_PRIORITIES[page_kind]
                if priority >= best_priority.get(url, 10_000):
                    continue
                if len(best_priority) >= self._config.max_candidates:
                    if not any(
                        item.code == LimitationCode.CANDIDATE_BUDGET_EXHAUSTED
                        for item in limitations
                    ):
                        limitations.append(
                            _limitation(
                                LimitationCode.CANDIDATE_BUDGET_EXHAUSTED,
                                "candidate_cap_reached",
                            )
                        )
                    continue
                discovered_order += 1
                best_priority[url] = priority
                heapq.heappush(
                    queue,
                    _Candidate(priority, discovered_order, url, page_kind),
                )

        if queue and fetch_attempts >= self._config.max_pages:
            limitations.append(
                _limitation(LimitationCode.PAGE_BUDGET_EXHAUSTED, "page_cap_reached")
            )
        return SiteInspection(
            root_url=root_url,
            robots_status=robots.status,
            pages=tuple(pages),
            limitations=tuple(limitations[:100]),
            discovered_document_urls=tuple(documents),
            page_fetch_attempts=fetch_attempts,
            policy_version=CRAWLER_POLICY_VERSION,
        )
