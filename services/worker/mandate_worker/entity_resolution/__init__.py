"""Entity-resolution website inspection boundary."""

from .crawler import CrawlerConfig, FetchClient, LegalPageCrawler
from .extraction import EXTRACTION_VERSION, extract_legal_page
from .models import (
    CrawlLimitation,
    DisclosureKind,
    ExtractionBasis,
    LegalDisclosure,
    LimitationCode,
    PageInspection,
    PageKind,
    RobotsStatus,
    SiteInspection,
)

__all__ = [
    "EXTRACTION_VERSION",
    "CrawlLimitation",
    "CrawlerConfig",
    "DisclosureKind",
    "ExtractionBasis",
    "FetchClient",
    "LegalDisclosure",
    "LegalPageCrawler",
    "LimitationCode",
    "PageInspection",
    "PageKind",
    "RobotsStatus",
    "SiteInspection",
    "extract_legal_page",
]
