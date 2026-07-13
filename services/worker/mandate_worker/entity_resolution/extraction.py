"""Deterministic extraction of legal-entity disclosures from untrusted HTML."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import DisclosureKind, ExtractionBasis, LegalDisclosure

EXTRACTION_VERSION = "entity-disclosures-regex-v1"
MAX_EXCERPT_CHARACTERS = 4000
MAX_LINKS_PER_PAGE = 250

CIN_PATTERN = re.compile(
    r"(?<![A-Z0-9])[UL][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}(?![A-Z0-9])", re.I
)
GSTIN_PATTERN = re.compile(
    r"(?<![A-Z0-9])[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[A-Z0-9](?![A-Z0-9])",
    re.I,
)
ISIN_PATTERN = re.compile(r"(?<![A-Z0-9])IN[A-Z0-9]{9}[0-9](?![A-Z0-9])", re.I)
TICKER_PATTERN = re.compile(
    r"\b(?P<exchange>NSE|BSE)\s*(?:code|symbol)?\s*[:\-]\s*(?P<ticker>[A-Z0-9&.-]{1,20})\b", re.I
)

LEGAL_SUFFIX = (
    r"(?:Private\s+Limited|Pvt\.?\s+Ltd\.?|Limited\s+Liability\s+Partnership|"
    r"Limited|Ltd\.?|LLP)"
)
ENTITY_NAME = rf"(?P<name>[A-Z0-9][A-Za-z0-9&'\u2019().,\- ]{{1,260}}?\s+{LEGAL_SUFFIX})"
STANDALONE_LEGAL_NAME = re.compile(rf"^\s*{ENTITY_NAME}\s*[.,|]?\s*$", re.I)
LABELLED_LEGAL_NAME = re.compile(
    rf"(?:legal\s+(?:entity|name)|company\s+name|corporate\s+identity)\s*[:\-]\s*{ENTITY_NAME}",
    re.I,
)
OWNER_OPERATOR = re.compile(
    rf"(?:owned\s+and\s+operated|operated|owned|managed)\s+by\s*[:\-]?\s*{ENTITY_NAME}",
    re.I,
)
DATA_CONTROLLER = re.compile(
    rf"(?:data\s+controller|controller\s+of\s+(?:your|the)\s+(?:personal\s+)?data)"
    rf"\s*(?:is|means|:|\-)\s*{ENTITY_NAME}",
    re.I,
)
COPYRIGHT_OWNER = re.compile(
    rf"(?:copyright|©|\(c\))\s*(?:©\s*)?(?:19|20)?[0-9]{{0,2}}(?:\s*[-\u2013]\s*(?:20)?[0-9]{{2}})?"
    rf"\s*{ENTITY_NAME}",
    re.I,
)
REGISTERED_OFFICE = re.compile(
    r"\bregistered\s+(?:office|address)\s*[:\-]\s*(?P<address>[^\n]{8,500})",
    re.I,
)
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


@dataclass(frozen=True, slots=True)
class DiscoveredLink:
    url: str
    label: str


@dataclass(frozen=True, slots=True)
class ExtractedPage:
    title: str
    excerpt: str
    disclosures: tuple[LegalDisclosure, ...]
    links: tuple[DiscoveredLink, ...]
    prompt_injection_suspected: bool
    captcha_detected: bool
    paywall_detected: bool
    automation_restricted: bool


def _normalise_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \t\r\n,;|-")


def _bounded_context(value: str, start: int, end: int) -> str:
    left = max(0, start - 300)
    right = min(len(value), end + 300)
    return _normalise_space(value[left:right])[:1000]


def _normalise_entity_name(value: str) -> str:
    return _normalise_space(value).rstrip(".,;|")[:500]


def _valid_isin(value: str) -> bool:
    expanded = "".join(str(int(character, 36)) for character in value.upper())
    total = 0
    for index, digit in enumerate(reversed(expanded)):
        number = int(digit)
        if index % 2 == 1:
            number *= 2
        total += number // 10 + number % 10
    return total % 10 == 0


class _DisclosureCollector:
    def __init__(self) -> None:
        self._values: list[LegalDisclosure] = []
        self._seen: set[tuple[DisclosureKind, str]] = set()

    def add(
        self,
        kind: DisclosureKind,
        value: str,
        context: str,
        basis: ExtractionBasis,
    ) -> None:
        normalised = _normalise_entity_name(value)
        clean_context = _normalise_space(context)[:1000]
        key = (kind, normalised.casefold())
        if not normalised or not clean_context or key in self._seen or len(self._values) >= 100:
            return
        self._seen.add(key)
        self._values.append(
            LegalDisclosure(kind=kind, value=normalised, context=clean_context, basis=basis)
        )

    def legal_name(
        self,
        value: str,
        context: str,
        basis: ExtractionBasis,
        related_kind: DisclosureKind | None = None,
    ) -> None:
        name = _normalise_entity_name(value)
        self.add(DisclosureKind.LEGAL_NAME, name, context, basis)
        if related_kind is not None:
            self.add(related_kind, name, context, basis)
        if re.search(r"\b(?:LLP|Limited\s+Liability\s+Partnership)\b", name, re.I):
            self.add(
                DisclosureKind.LEGAL_FORM_WARNING,
                "llp_out_of_company_scope",
                context,
                basis,
            )

    def result(self) -> tuple[LegalDisclosure, ...]:
        return tuple(self._values)


def _json_ld_objects(value: object) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, dict):
        mapping = cast(dict[str, Any], value)
        yield mapping
        graph = mapping.get("@graph")
        if graph is not None:
            yield from _json_ld_objects(graph)
    elif isinstance(value, list):
        for item in value:
            yield from _json_ld_objects(item)


def _is_organisation(value: Mapping[str, Any]) -> bool:
    raw_type = value.get("@type")
    types = raw_type if isinstance(raw_type, list) else [raw_type]
    return any(
        isinstance(item, str)
        and item.casefold() in {"organization", "corporation", "localbusiness"}
        for item in types
    )


def _json_ld_address(value: object) -> str | None:
    if isinstance(value, str):
        return _normalise_space(value)
    if not isinstance(value, dict):
        return None
    address = cast(dict[str, Any], value)
    fields = (
        "streetAddress",
        "addressLocality",
        "addressRegion",
        "postalCode",
        "addressCountry",
    )
    parts = [_normalise_space(str(address[field])) for field in fields if address.get(field)]
    return ", ".join(parts) or None


def _extract_json_ld(soup: BeautifulSoup, collector: _DisclosureCollector) -> None:
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = script.string or script.get_text(" ", strip=True)
        if not raw or len(raw) > 200_000:
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        for item in _json_ld_objects(payload):
            if not _is_organisation(item):
                continue
            context = _normalise_space(raw)[:1000]
            name = item.get("legalName") or item.get("name")
            if isinstance(name, str) and re.search(LEGAL_SUFFIX, name, re.I):
                collector.legal_name(name, context, ExtractionBasis.JSON_LD)
            address = _json_ld_address(item.get("address"))
            if address:
                collector.add(
                    DisclosureKind.REGISTERED_OFFICE,
                    address,
                    context,
                    ExtractionBasis.JSON_LD,
                )
            for key in ("taxID", "vatID"):
                identifier = item.get(key)
                if not isinstance(identifier, str):
                    continue
                for match in CIN_PATTERN.finditer(identifier):
                    collector.add(
                        DisclosureKind.CIN,
                        match.group().upper(),
                        context,
                        ExtractionBasis.JSON_LD,
                    )
                for match in GSTIN_PATTERN.finditer(identifier):
                    collector.add(
                        DisclosureKind.GSTIN,
                        match.group().upper(),
                        context,
                        ExtractionBasis.JSON_LD,
                    )


def _remove_untrusted_markup(soup: BeautifulSoup) -> None:
    for element in soup.find_all(("script", "style", "noscript", "template", "svg", "iframe")):
        element.decompose()
    for element in soup.find_all(True):
        if not isinstance(element, Tag):
            continue
        if element.parent is None or element.attrs is None:
            continue
        style = str(element.get("style", "")).replace(" ", "").casefold()
        if (
            element.has_attr("hidden")
            or str(element.get("aria-hidden", "")).casefold() == "true"
            or "display:none" in style
            or "visibility:hidden" in style
        ):
            element.decompose()


def _extract_labelled_names(text: str, collector: _DisclosureCollector) -> None:
    patterns = (
        (OWNER_OPERATOR, DisclosureKind.OWNER_OPERATOR),
        (DATA_CONTROLLER, DisclosureKind.DATA_CONTROLLER),
        (COPYRIGHT_OWNER, DisclosureKind.COPYRIGHT_OWNER),
        (LABELLED_LEGAL_NAME, None),
    )
    for pattern, related_kind in patterns:
        for match in pattern.finditer(text):
            collector.legal_name(
                match.group("name"),
                _bounded_context(text, match.start(), match.end()),
                ExtractionBasis.LABEL,
                related_kind,
            )
    for line in text.splitlines():
        normalised_line = _normalise_space(line)
        if re.search(
            r"\b(?:by|controller|copyright|legal\s+(?:entity|name)|company\s+name)\b|©",
            normalised_line,
            re.I,
        ):
            continue
        standalone_match = STANDALONE_LEGAL_NAME.fullmatch(normalised_line)
        if standalone_match is not None:
            collector.legal_name(
                standalone_match.group("name"),
                normalised_line,
                ExtractionBasis.REGEX,
            )


def _extract_identifiers(text: str, collector: _DisclosureCollector) -> None:
    for pattern, kind in (
        (CIN_PATTERN, DisclosureKind.CIN),
        (GSTIN_PATTERN, DisclosureKind.GSTIN),
    ):
        for match in pattern.finditer(text):
            collector.add(
                kind,
                match.group().upper(),
                _bounded_context(text, match.start(), match.end()),
                ExtractionBasis.REGEX,
            )
    for match in ISIN_PATTERN.finditer(text):
        value = match.group().upper()
        if _valid_isin(value):
            collector.add(
                DisclosureKind.ISIN,
                value,
                _bounded_context(text, match.start(), match.end()),
                ExtractionBasis.REGEX,
            )
    for match in TICKER_PATTERN.finditer(text):
        value = f"{match.group('exchange').upper()}:{match.group('ticker').upper()}"
        collector.add(
            DisclosureKind.STOCK_TICKER,
            value,
            _bounded_context(text, match.start(), match.end()),
            ExtractionBasis.LABEL,
        )


def _extract_addresses(text: str, collector: _DisclosureCollector) -> None:
    for match in REGISTERED_OFFICE.finditer(text):
        collector.add(
            DisclosureKind.REGISTERED_OFFICE,
            match.group("address")[:500],
            _bounded_context(text, match.start(), match.end()),
            ExtractionBasis.LABEL,
        )


def _extract_links(soup: BeautifulSoup, base_url: str) -> tuple[DiscoveredLink, ...]:
    links: list[DiscoveredLink] = []
    seen: set[str] = set()
    for anchor in soup.find_all("a", href=True):
        if len(links) >= MAX_LINKS_PER_PAGE or not isinstance(anchor, Tag):
            break
        raw_rel = anchor.get("rel")
        rel_values = raw_rel if isinstance(raw_rel, list) else [raw_rel]
        rel = {str(item).casefold() for item in rel_values if item is not None}
        if "nofollow" in rel:
            continue
        href = anchor.get("href")
        if not isinstance(href, str):
            continue
        url = urljoin(base_url, href.strip())
        if url in seen:
            continue
        seen.add(url)
        label = _normalise_space(anchor.get_text(" ", strip=True))[:300]
        links.append(DiscoveredLink(url=url, label=label))
    return tuple(links)


def extract_legal_page(body: bytes, base_url: str) -> ExtractedPage:
    """Extract bounded facts and links while treating every byte as untrusted data."""

    decoded = body.decode("utf-8", errors="replace")
    raw_suspicious = any(pattern.search(decoded) for pattern in PROMPT_INJECTION_PATTERNS)
    soup = BeautifulSoup(body, "html.parser")
    collector = _DisclosureCollector()
    _extract_json_ld(soup, collector)
    _remove_untrusted_markup(soup)

    title_tag = soup.find("title")
    title = _normalise_space(title_tag.get_text(" ", strip=True)) if title_tag else "Untitled page"
    title = title[:500] or "Untitled page"
    visible_text = "\n".join(
        line
        for line in (_normalise_space(part) for part in soup.get_text("\n").splitlines())
        if line
    )
    _extract_labelled_names(visible_text, collector)
    _extract_identifiers(visible_text, collector)
    _extract_addresses(visible_text, collector)

    excerpt = _normalise_space(visible_text)[:MAX_EXCERPT_CHARACTERS] or title
    search_surface = f"{decoded[:500_000]}\n{visible_text}"
    return ExtractedPage(
        title=title,
        excerpt=excerpt,
        disclosures=collector.result(),
        links=_extract_links(soup, base_url),
        prompt_injection_suspected=raw_suspicious,
        captcha_detected=any(pattern.search(search_surface) for pattern in CAPTCHA_PATTERNS),
        paywall_detected=any(pattern.search(search_surface) for pattern in PAYWALL_PATTERNS),
        automation_restricted=any(
            pattern.search(visible_text) for pattern in AUTOMATION_RESTRICTION_PATTERNS
        ),
    )
