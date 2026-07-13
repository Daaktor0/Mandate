"""Entity-resolution website inspection boundary."""

from .candidates import (
    CandidateGenerationError,
    CandidateGenerationResult,
    CandidateGeneratorConfig,
    CandidateScoreAudit,
    CandidateSignalKind,
    EntityCandidateGenerator,
    ResolutionGuidanceCode,
    ResolutionSignal,
    ScoringFactor,
    ScoringFacts,
    confidence_label,
    score_candidate,
)
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
    "CandidateGenerationError",
    "CandidateGenerationResult",
    "CandidateGeneratorConfig",
    "CandidateScoreAudit",
    "CandidateSignalKind",
    "CrawlLimitation",
    "CrawlerConfig",
    "DisclosureKind",
    "EntityCandidateGenerator",
    "ExtractionBasis",
    "FetchClient",
    "LegalDisclosure",
    "LegalPageCrawler",
    "LimitationCode",
    "PageInspection",
    "PageKind",
    "ResolutionGuidanceCode",
    "ResolutionSignal",
    "RobotsStatus",
    "ScoringFactor",
    "ScoringFacts",
    "SiteInspection",
    "confidence_label",
    "extract_legal_page",
    "score_candidate",
]
