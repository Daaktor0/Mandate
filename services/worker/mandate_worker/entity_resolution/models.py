"""Typed, bounded outputs from company-controlled website inspection."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class PageKind(StrEnum):
    HOME = "home"
    CONTACT = "contact"
    PRIVACY = "privacy"
    TERMS = "terms"
    LEGAL_NOTICE = "legal_notice"
    COOKIE_POLICY = "cookie_policy"
    INVESTOR_RELATIONS = "investor_relations"
    GOVERNANCE = "governance"
    ANNUAL_REPORT = "annual_report"
    CAREERS = "careers"
    CONSUMER_TERMS = "consumer_terms"
    CORPORATE_DISCLOSURE = "corporate_disclosure"


class DisclosureKind(StrEnum):
    LEGAL_NAME = "legal_name"
    CIN = "cin"
    GSTIN = "gstin"
    REGISTERED_OFFICE = "registered_office"
    COPYRIGHT_OWNER = "copyright_owner"
    DATA_CONTROLLER = "data_controller"
    OWNER_OPERATOR = "owner_operator"
    STOCK_TICKER = "stock_ticker"
    ISIN = "isin"
    LEGAL_FORM_WARNING = "legal_form_warning"


class ExtractionBasis(StrEnum):
    REGEX = "regex"
    LABEL = "label"
    JSON_LD = "json_ld"


class LimitationCode(StrEnum):
    ROBOTS_UNAVAILABLE = "robots_unavailable"
    ROBOTS_DENIED = "robots_denied"
    CRAWL_DELAY_EXCEEDS_BUDGET = "crawl_delay_exceeds_budget"
    FETCH_FAILED = "fetch_failed"
    HTTP_STATUS = "http_status"
    ACCESS_CONTROLLED = "access_controlled"
    CAPTCHA_DETECTED = "captcha_detected"
    PAYWALL_DETECTED = "paywall_detected"
    TERMS_RESTRICT_AUTOMATION = "terms_restrict_automation"
    OFFSITE_REDIRECT = "offsite_redirect"
    UNSUPPORTED_DOCUMENT = "unsupported_document"
    PAGE_TOO_LARGE = "page_too_large"
    PAGE_BUDGET_EXHAUSTED = "page_budget_exhausted"
    CANDIDATE_BUDGET_EXHAUSTED = "candidate_budget_exhausted"


class RobotsStatus(StrEnum):
    ALLOWED = "allowed"
    ABSENT = "absent"
    DENIED = "denied"
    UNAVAILABLE = "unavailable"


class LegalDisclosure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: DisclosureKind
    value: str = Field(min_length=1, max_length=500)
    context: str = Field(min_length=1, max_length=1000)
    basis: ExtractionBasis


class PageInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    requested_url: str = Field(min_length=1, max_length=2048)
    canonical_url: str = Field(min_length=1, max_length=2048)
    page_kind: PageKind
    status_code: int = Field(ge=200, le=299)
    title: str = Field(min_length=1, max_length=500)
    publisher: str = Field(min_length=1, max_length=300)
    content_type: str = Field(min_length=1, max_length=100)
    content_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    excerpt: str = Field(min_length=1, max_length=4000)
    disclosures: tuple[LegalDisclosure, ...] = Field(max_length=100)
    prompt_injection_suspected: bool
    company_controlled: bool
    extraction_version: str = Field(min_length=1, max_length=100)


class CrawlLimitation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: LimitationCode
    url: str | None = Field(default=None, max_length=2048)
    detail_code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_.:-]+$")


class SiteInspection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    root_url: str = Field(min_length=1, max_length=2048)
    robots_status: RobotsStatus
    pages: tuple[PageInspection, ...] = Field(max_length=15)
    limitations: tuple[CrawlLimitation, ...] = Field(max_length=100)
    discovered_document_urls: tuple[str, ...] = Field(max_length=100)
    page_fetch_attempts: int = Field(ge=0, le=15)
    policy_version: str = Field(min_length=1, max_length=100)
