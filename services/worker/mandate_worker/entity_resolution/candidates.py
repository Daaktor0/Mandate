"""Deterministic legal-entity candidate generation and confidence scoring."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal, Self
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from mandate_schemas.generated import (
    EntityCandidate,
    EntityCandidateCompanyType,
    EntityCandidateConfidenceLabel,
    EntityCandidateEvidenceSnippetsItem,
    EntityCandidateListedStatus,
)
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator

from mandate_worker.providers.company_data import (
    ATTESTR_MASTER_URL,
    ATTESTR_SEARCH_URL,
    CIN_PATTERN,
    CompanyDataOperation,
    CompanyDataProvider,
    CompanyDataRecord,
    CompanyDataResponse,
)

from .models import DisclosureKind, LegalDisclosure, PageInspection, SiteInspection

MAX_CANDIDATES: Final = 20
MAX_PROVIDER_QUERIES: Final = 20
MAX_PROVIDER_CALLS: Final = 40
MAX_EVIDENCE_PER_CANDIDATE: Final = 20
CANDIDATE_NAMESPACE: Final = UUID("7c20b8e4-290f-5f26-848d-b49a73fe791d")
EVIDENCE_NAMESPACE: Final = UUID("c3529550-3ee8-5bc4-966d-4346ded3fa37")
FIXTURE_SOURCE_URL: Final = "https://fixtures.mandate.local/company-data/smoke"


class ScoringFactor(StrEnum):
    EXACT_LEGAL_NAME_AND_CIN_ON_DOMAIN = "exact_legal_name_and_cin_on_domain"
    ADDRESS_CONTACT_MATCHES_MASTER_DATA = "address_contact_matches_master_data"
    COMPANY_CONTROLLED_LEGAL_PAGE = "company_controlled_legal_page"
    OFFICIAL_REGULATOR_EXCHANGE_LINKS_DOMAIN = "official_regulator_exchange_links_domain"
    DIRECTORS_PROMOTERS_BUSINESS_MATCH = "directors_promoters_business_match"
    CREDIBLE_CORROBORATION = "credible_corroboration"
    INACTIVE_STATUS = "inactive_status"
    CONFLICTING_REGISTERED_OFFICE = "conflicting_registered_office"
    INCOMPATIBLE_BUSINESS_DESCRIPTION = "incompatible_business_description"
    NAME_ONLY_MATCH = "name_only_match"
    COMMON_NAME_ADVERSE_AMBIGUITY = "common_name_adverse_ambiguity"


POSITIVE_WEIGHTS: Final[Mapping[ScoringFactor, int]] = MappingProxyType(
    {
        ScoringFactor.EXACT_LEGAL_NAME_AND_CIN_ON_DOMAIN: 35,
        ScoringFactor.ADDRESS_CONTACT_MATCHES_MASTER_DATA: 20,
        ScoringFactor.COMPANY_CONTROLLED_LEGAL_PAGE: 15,
        ScoringFactor.OFFICIAL_REGULATOR_EXCHANGE_LINKS_DOMAIN: 15,
        ScoringFactor.DIRECTORS_PROMOTERS_BUSINESS_MATCH: 10,
        ScoringFactor.CREDIBLE_CORROBORATION: 5,
    }
)
NEGATIVE_WEIGHTS: Final[Mapping[ScoringFactor, int]] = MappingProxyType(
    {
        ScoringFactor.INACTIVE_STATUS: -15,
        ScoringFactor.CONFLICTING_REGISTERED_OFFICE: -10,
        ScoringFactor.INCOMPATIBLE_BUSINESS_DESCRIPTION: -15,
        ScoringFactor.NAME_ONLY_MATCH: -20,
        ScoringFactor.COMMON_NAME_ADVERSE_AMBIGUITY: -10,
    }
)
ALL_FACTORS: Final = tuple((*POSITIVE_WEIGHTS, *NEGATIVE_WEIGHTS))


class CandidateSignalKind(StrEnum):
    OFFICIAL_DOMAIN_LINK = "official_domain_link"
    DIRECTOR_PROMOTER_BUSINESS_MATCH = "director_promoter_business_match"
    CREDIBLE_CORROBORATION = "credible_corroboration"
    CONFLICTING_REGISTERED_OFFICE = "conflicting_registered_office"
    INCOMPATIBLE_BUSINESS = "incompatible_business"
    COMMON_NAME_ADVERSE_AMBIGUITY = "common_name_adverse_ambiguity"


class CandidateGenerationError(RuntimeError):
    """Stable terminal candidate-generation failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


SIGNAL_FACTORS: Final[Mapping[CandidateSignalKind, ScoringFactor]] = MappingProxyType(
    {
        CandidateSignalKind.OFFICIAL_DOMAIN_LINK: (
            ScoringFactor.OFFICIAL_REGULATOR_EXCHANGE_LINKS_DOMAIN
        ),
        CandidateSignalKind.DIRECTOR_PROMOTER_BUSINESS_MATCH: (
            ScoringFactor.DIRECTORS_PROMOTERS_BUSINESS_MATCH
        ),
        CandidateSignalKind.CREDIBLE_CORROBORATION: ScoringFactor.CREDIBLE_CORROBORATION,
        CandidateSignalKind.CONFLICTING_REGISTERED_OFFICE: (
            ScoringFactor.CONFLICTING_REGISTERED_OFFICE
        ),
        CandidateSignalKind.INCOMPATIBLE_BUSINESS: (
            ScoringFactor.INCOMPATIBLE_BUSINESS_DESCRIPTION
        ),
        CandidateSignalKind.COMMON_NAME_ADVERSE_AMBIGUITY: (
            ScoringFactor.COMMON_NAME_ADVERSE_AMBIGUITY
        ),
    }
)


class ScoringFacts(BaseModel):
    """Boolean scoring inputs; no subjective rationale or model output is accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    exact_legal_name_and_cin_on_domain: bool = False
    address_contact_matches_master_data: bool = False
    company_controlled_legal_page: bool = False
    official_regulator_exchange_links_domain: bool = False
    directors_promoters_business_match: bool = False
    credible_corroboration: bool = False
    inactive_status: bool = False
    conflicting_registered_office: bool = False
    incompatible_business_description: bool = False
    name_only_match: bool = False
    common_name_adverse_ambiguity: bool = False

    def applies(self, factor: ScoringFactor) -> bool:
        return bool(getattr(self, factor.value))


class FactorAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    factor: ScoringFactor
    applied: bool
    adjustment: int = Field(ge=-20, le=35)

    @model_validator(mode="after")
    def adjustment_matches_application(self) -> Self:
        expected = POSITIVE_WEIGHTS.get(self.factor, NEGATIVE_WEIGHTS.get(self.factor))
        if expected is None:
            raise ValueError("unknown scoring factor")
        if self.adjustment != (expected if self.applied else 0):
            raise ValueError("scoring adjustment does not match the factor table")
        return self


class ScoreCalculation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    positive_total: int = Field(ge=0, le=100)
    negative_total: int = Field(ge=-70, le=0)
    score: int = Field(ge=0, le=100)
    label: EntityCandidateConfidenceLabel
    adjustments: tuple[FactorAdjustment, ...] = Field(min_length=11, max_length=11)


class FactorDecision(BaseModel):
    """Concise, auditable scoring decision; never a hidden reasoning trace."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    factor: ScoringFactor
    applied: bool
    adjustment: int = Field(ge=-20, le=35)
    evidence_ids: tuple[UUID, ...] = Field(max_length=20)
    rationale_code: str = Field(min_length=1, max_length=100, pattern=r"^[a-z0-9_.-]+$")


class CandidateScoreAudit(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    candidate_id: UUID = Field(alias="candidateId")
    scoring_version: Literal["entity-confidence-v1"] = Field(
        default="entity-confidence-v1", alias="scoringVersion"
    )
    positive_total: int = Field(alias="positiveTotal", ge=0, le=100)
    negative_total: int = Field(alias="negativeTotal", ge=-70, le=0)
    final_score: int = Field(alias="finalScore", ge=0, le=100)
    decisions: tuple[FactorDecision, ...] = Field(min_length=11, max_length=11)


class ResolutionGuidanceCode(StrEnum):
    LEGAL_NAME_OR_CIN_REQUIRED = "legal_name_or_cin_required"
    CONFIRM_CANDIDATE = "confirm_candidate"


class CandidateGenerationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    candidates: tuple[EntityCandidate, ...] = Field(max_length=MAX_CANDIDATES)
    score_audits: tuple[CandidateScoreAudit, ...] = Field(alias="scoreAudits")
    provider_queries: int = Field(alias="providerQueries", ge=0, le=MAX_PROVIDER_QUERIES)
    provider_calls: int = Field(alias="providerCalls", ge=0, le=MAX_PROVIDER_CALLS)
    requires_user_confirmation: Literal[True] = Field(
        default=True, alias="requiresUserConfirmation"
    )
    needs_identity_input: bool = Field(alias="needsIdentityInput")
    guidance_code: ResolutionGuidanceCode = Field(alias="guidanceCode")

    @model_validator(mode="after")
    def candidates_and_audits_align(self) -> Self:
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        audit_ids = [audit.candidate_id for audit in self.score_audits]
        if len(candidate_ids) != len(set(candidate_ids)) or candidate_ids != audit_ids:
            raise ValueError("candidate score audits must align one-to-one in ranked order")
        if self.needs_identity_input != (not self.candidates):
            raise ValueError("identity input is required exactly when no candidates exist")
        expected = (
            ResolutionGuidanceCode.LEGAL_NAME_OR_CIN_REQUIRED
            if self.needs_identity_input
            else ResolutionGuidanceCode.CONFIRM_CANDIDATE
        )
        if self.guidance_code is not expected:
            raise ValueError("resolution guidance does not match the candidate outcome")
        return self


class ResolutionSignal(BaseModel):
    """Pre-classified public-source signal supplied by later retrieval adapters."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    kind: CandidateSignalKind
    candidate_cin: str | None = Field(default=None, alias="candidateCin")
    candidate_legal_name: str | None = Field(
        default=None, alias="candidateLegalName", min_length=1, max_length=300
    )
    source_tier: int = Field(alias="sourceTier", ge=1, le=5)
    evidence: EntityCandidateEvidenceSnippetsItem

    @field_validator("candidate_cin", mode="before")
    @classmethod
    def normalise_candidate_cin(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("candidate CIN must be a string")
        normalised = value.strip().upper()
        if CIN_PATTERN.fullmatch(normalised) is None:
            raise ValueError("candidate CIN is invalid")
        return normalised

    @model_validator(mode="after")
    def validate_signal_scope_and_tier(self) -> Self:
        if self.candidate_cin is None and self.candidate_legal_name is None:
            raise ValueError("signal must identify a candidate by CIN or legal name")
        if self.kind is CandidateSignalKind.OFFICIAL_DOMAIN_LINK and self.source_tier != 1:
            raise ValueError("official regulator/exchange signal must be source tier 1")
        if self.kind is CandidateSignalKind.CREDIBLE_CORROBORATION and self.source_tier > 3:
            raise ValueError("credible corroboration must be source tier 3 or stronger")
        return self


class CandidateGeneratorConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_cin_queries: int = Field(default=10, ge=1, le=10)
    max_name_queries: int = Field(default=10, ge=1, le=10)
    max_candidates: int = Field(default=MAX_CANDIDATES, ge=1, le=MAX_CANDIDATES)
    provider_result_limit: int = Field(default=10, ge=1, le=20)


@dataclass(slots=True)
class _CandidateAggregate:
    record: CompanyDataRecord
    matched_by_name: bool = False
    matched_by_cin: bool = False
    provider_evidence: dict[UUID, EntityCandidateEvidenceSnippetsItem] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _CandidateSiteFacts:
    exact_name_ids: frozenset[UUID]
    legal_page_ids: frozenset[UUID]
    cin_ids: frozenset[UUID]
    address_match_ids: frozenset[UUID]
    address_conflict_ids: frozenset[UUID]
    evidence: tuple[EntityCandidateEvidenceSnippetsItem, ...]


def score_candidate(facts: ScoringFacts) -> ScoreCalculation:
    """Apply the verbatim factor table and threshold labels."""

    adjustments = tuple(
        FactorAdjustment(
            factor=factor,
            applied=facts.applies(factor),
            adjustment=(
                POSITIVE_WEIGHTS.get(factor, NEGATIVE_WEIGHTS.get(factor, 0))
                if facts.applies(factor)
                else 0
            ),
        )
        for factor in ALL_FACTORS
    )
    positive_total = sum(item.adjustment for item in adjustments if item.adjustment > 0)
    negative_total = sum(item.adjustment for item in adjustments if item.adjustment < 0)
    score = min(100, max(0, positive_total + negative_total))
    return ScoreCalculation(
        positive_total=positive_total,
        negative_total=negative_total,
        score=score,
        label=confidence_label(score),
        adjustments=adjustments,
    )


def confidence_label(score: int) -> EntityCandidateConfidenceLabel:
    if not 0 <= score <= 100:
        raise ValueError("confidence score must be between 0 and 100")
    if score >= 75:
        return EntityCandidateConfidenceLabel.STRONG_MATCH
    if score >= 50:
        return EntityCandidateConfidenceLabel.PROBABLE_MATCH
    if score >= 25:
        return EntityCandidateConfidenceLabel.AMBIGUOUS
    return EntityCandidateConfidenceLabel.INSUFFICIENT_EVIDENCE


@dataclass(frozen=True, slots=True)
class EntityCandidateGenerator:
    provider: CompanyDataProvider
    config: CandidateGeneratorConfig = field(default_factory=CandidateGeneratorConfig)

    async def generate(
        self,
        *,
        supplied_legal_name: str | None = None,
        supplied_cin: str | None = None,
        site_inspection: SiteInspection | None = None,
        signals: Sequence[ResolutionSignal] = (),
    ) -> CandidateGenerationResult:
        names = _candidate_names(supplied_legal_name, site_inspection)[
            : self.config.max_name_queries
        ]
        cins = _candidate_cins(supplied_cin, site_inspection)[: self.config.max_cin_queries]
        aggregates: dict[str, _CandidateAggregate] = {}
        provider_queries = 0
        provider_calls = 0

        for cin in cins:
            if len(aggregates) >= self.config.max_candidates:
                break
            response = await self.provider.lookup_by_cin(cin)
            provider_queries += 1
            provider_calls += response.provider_calls
            self._ingest_response(aggregates, response)

        for name in names:
            if len(aggregates) >= self.config.max_candidates:
                break
            remaining = self.config.max_candidates - len(aggregates)
            response = await self.provider.search_by_name(
                name,
                limit=min(self.config.provider_result_limit, max(1, remaining)),
            )
            provider_queries += 1
            provider_calls += response.provider_calls
            self._ingest_response(aggregates, response)

        scored = [
            self._score_aggregate(aggregate, site_inspection=site_inspection, signals=signals)
            for aggregate in aggregates.values()
        ]
        scored.sort(
            key=lambda item: (
                -item[0].confidence_score,
                item[0].legal_name.casefold(),
                item[0].cin or "",
            )
        )
        candidates = tuple(item[0] for item in scored)
        audits = tuple(item[1] for item in scored)
        needs_input = not candidates
        return CandidateGenerationResult(
            candidates=candidates,
            scoreAudits=audits,
            providerQueries=provider_queries,
            providerCalls=provider_calls,
            needsIdentityInput=needs_input,
            guidanceCode=(
                ResolutionGuidanceCode.LEGAL_NAME_OR_CIN_REQUIRED
                if needs_input
                else ResolutionGuidanceCode.CONFIRM_CANDIDATE
            ),
        )

    def _ingest_response(
        self,
        aggregates: dict[str, _CandidateAggregate],
        response: CompanyDataResponse,
    ) -> None:
        for record in response.records:
            aggregate = aggregates.get(record.cin)
            if aggregate is None:
                if len(aggregates) >= self.config.max_candidates:
                    continue
                aggregate = _CandidateAggregate(record=record)
                aggregates[record.cin] = aggregate
            else:
                aggregate.record = _merge_company_records(aggregate.record, record)
            if response.operation is CompanyDataOperation.SEARCH_BY_NAME:
                aggregate.matched_by_name = True
            else:
                aggregate.matched_by_cin = True
            evidence = _provider_evidence(response, record)
            aggregate.provider_evidence[evidence.evidence_id] = evidence

    def _score_aggregate(
        self,
        aggregate: _CandidateAggregate,
        *,
        site_inspection: SiteInspection | None,
        signals: Sequence[ResolutionSignal],
    ) -> tuple[EntityCandidate, CandidateScoreAudit]:
        record = aggregate.record
        site = _site_facts(record, site_inspection)
        matching_signals = tuple(
            signal for signal in signals if _signal_matches_record(signal, record)
        )
        signal_factors = {SIGNAL_FACTORS[signal.kind] for signal in matching_signals}
        stronger_linkage = any(
            (
                site.exact_name_ids and site.cin_ids,
                site.address_match_ids,
                ScoringFactor.OFFICIAL_REGULATOR_EXCHANGE_LINKS_DOMAIN in signal_factors,
                ScoringFactor.DIRECTORS_PROMOTERS_BUSINESS_MATCH in signal_factors,
                ScoringFactor.CREDIBLE_CORROBORATION in signal_factors,
            )
        )
        inactive = record.active is False or _status_is_inactive(record.status)
        facts = ScoringFacts(
            exact_legal_name_and_cin_on_domain=bool(site.exact_name_ids and site.cin_ids),
            address_contact_matches_master_data=bool(site.address_match_ids),
            company_controlled_legal_page=bool(site.legal_page_ids),
            official_regulator_exchange_links_domain=(
                ScoringFactor.OFFICIAL_REGULATOR_EXCHANGE_LINKS_DOMAIN in signal_factors
            ),
            directors_promoters_business_match=(
                ScoringFactor.DIRECTORS_PROMOTERS_BUSINESS_MATCH in signal_factors
            ),
            credible_corroboration=(ScoringFactor.CREDIBLE_CORROBORATION in signal_factors),
            inactive_status=inactive,
            conflicting_registered_office=(
                bool(site.address_conflict_ids)
                or ScoringFactor.CONFLICTING_REGISTERED_OFFICE in signal_factors
            ),
            incompatible_business_description=(
                ScoringFactor.INCOMPATIBLE_BUSINESS_DESCRIPTION in signal_factors
            ),
            name_only_match=(
                aggregate.matched_by_name and not aggregate.matched_by_cin and not stronger_linkage
            ),
            common_name_adverse_ambiguity=(
                ScoringFactor.COMMON_NAME_ADVERSE_AMBIGUITY in signal_factors
            ),
        )
        calculation = score_candidate(facts)
        evidence_by_factor = _factor_evidence(
            site,
            matching_signals,
            tuple(aggregate.provider_evidence),
            facts,
        )
        signal_evidence = tuple(signal.evidence for signal in matching_signals)
        evidence = _dedupe_evidence(
            (*site.evidence, *signal_evidence, *aggregate.provider_evidence.values())
        )[:MAX_EVIDENCE_PER_CANDIDATE]
        candidate_id = _candidate_id(record)
        candidate = EntityCandidate(
            schemaVersion=1,
            candidateId=candidate_id,
            legalName=record.legal_name,
            formerNames=list(record.former_names),
            cin=record.cin,
            companyType=_company_type(record),
            listedStatus=(
                EntityCandidateListedStatus.LISTED
                if _is_listed(record)
                else EntityCandidateListedStatus.UNLISTED
            ),
            status=record.status,
            registeredOfficeState=record.registered_office_state,
            registeredOfficeSummary=record.registered_office_summary,
            primaryDomain=_primary_domain(site_inspection) if site.evidence else None,
            brandNames=[],
            confidenceScore=calculation.score,
            confidenceLabel=calculation.label,
            evidenceSnippets=list(evidence),
            conflicts=_conflict_messages(facts),
        )
        decisions = tuple(
            FactorDecision(
                factor=adjustment.factor,
                applied=adjustment.applied,
                adjustment=adjustment.adjustment,
                evidence_ids=tuple(sorted(evidence_by_factor.get(adjustment.factor, ()), key=str))[
                    :20
                ],
                rationale_code=(
                    f"entity_score.{adjustment.factor.value}."
                    f"{'applied' if adjustment.applied else 'not_applied'}"
                ),
            )
            for adjustment in calculation.adjustments
        )
        audit = CandidateScoreAudit(
            candidateId=candidate_id,
            positiveTotal=calculation.positive_total,
            negativeTotal=calculation.negative_total,
            finalScore=calculation.score,
            decisions=decisions,
        )
        return candidate, audit


def _candidate_names(
    supplied_legal_name: str | None,
    inspection: SiteInspection | None,
) -> tuple[str, ...]:
    values: list[str] = []
    if supplied_legal_name is not None:
        values.append(_clean_name(supplied_legal_name))
    if inspection is not None:
        for page in inspection.pages:
            for disclosure in page.disclosures:
                if disclosure.kind is not DisclosureKind.LEGAL_NAME:
                    continue
                try:
                    values.append(_clean_name(disclosure.value))
                except ValueError:
                    continue
    return _unique_names(values)


def _candidate_cins(
    supplied_cin: str | None,
    inspection: SiteInspection | None,
) -> tuple[str, ...]:
    values: list[str] = []
    if supplied_cin is not None:
        values.append(_clean_cin(supplied_cin))
    if inspection is not None:
        for page in inspection.pages:
            for disclosure in page.disclosures:
                if disclosure.kind is not DisclosureKind.CIN:
                    continue
                try:
                    values.append(_clean_cin(disclosure.value))
                except ValueError:
                    continue
    return _unique_strings(values)


def _unique_strings(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return tuple(result)


def _unique_names(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean_name(value)
        key = _normalised_name(cleaned)
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return tuple(result)


def _clean_name(value: str) -> str:
    name = " ".join(value.split())
    if not name or len(name) > 300:
        raise ValueError("legal name is empty or too long")
    return name


def _clean_cin(value: str) -> str:
    cin = value.strip().upper()
    if CIN_PATTERN.fullmatch(cin) is None:
        raise ValueError("CIN is invalid")
    return cin


def _normalised_name(value: str) -> str:
    name = value.casefold()
    name = re.sub(r"\bpvt\.?\b", "private", name)
    name = re.sub(r"\bltd\.?\b", "limited", name)
    return re.sub(r"[^a-z0-9]+", " ", name).strip()


def _candidate_id(record: CompanyDataRecord) -> UUID:
    key = (
        f"{record.cin}|{_normalised_name(record.legal_name)}|{record.registered_office_state or ''}"
    )
    return uuid5(CANDIDATE_NAMESPACE, key)


def _evidence_id(key: str) -> UUID:
    return uuid5(EVIDENCE_NAMESPACE, key)


def _provider_source_url(response: CompanyDataResponse) -> str:
    if response.provider == "fixture":
        return FIXTURE_SOURCE_URL
    if response.provider == "attestr":
        return (
            ATTESTR_SEARCH_URL
            if response.operation is CompanyDataOperation.SEARCH_BY_NAME
            else ATTESTR_MASTER_URL
        )
    raise CandidateGenerationError("candidate_provider_provenance_not_allowlisted")


def _provider_evidence(
    response: CompanyDataResponse,
    record: CompanyDataRecord,
) -> EntityCandidateEvidenceSnippetsItem:
    detail = f"Compatible company-data source returned {record.legal_name} ({record.cin})"
    if record.status:
        detail += f" with status {record.status}"
    if record.registered_office_state:
        detail += f" and registered-office state {record.registered_office_state}"
    detail += "."
    source_url = _provider_source_url(response)
    return EntityCandidateEvidenceSnippetsItem(
        evidenceId=_evidence_id(
            f"provider|{response.provider}|{response.operation.value}|{record.cin}|{detail}"
        ),
        snippet=detail,
        sourceUrl=AnyHttpUrl(source_url),
        companyControlled=False,
    )


def _page_evidence(
    page: PageInspection,
    disclosure: LegalDisclosure,
) -> EntityCandidateEvidenceSnippetsItem:
    return EntityCandidateEvidenceSnippetsItem(
        evidenceId=_evidence_id(
            f"site|{page.canonical_url}|{page.content_hash}|{disclosure.kind.value}|"
            f"{disclosure.value}|{disclosure.context}"
        ),
        snippet=disclosure.context,
        sourceUrl=AnyHttpUrl(page.canonical_url),
        companyControlled=page.company_controlled,
    )


def _site_facts(
    record: CompanyDataRecord,
    inspection: SiteInspection | None,
) -> _CandidateSiteFacts:
    if inspection is None:
        return _CandidateSiteFacts(
            exact_name_ids=frozenset(),
            legal_page_ids=frozenset(),
            cin_ids=frozenset(),
            address_match_ids=frozenset(),
            address_conflict_ids=frozenset(),
            evidence=(),
        )
    current_name = _normalised_name(record.legal_name)
    former_names = {_normalised_name(name) for name in record.former_names}
    exact_name_ids: set[UUID] = set()
    legal_page_ids: set[UUID] = set()
    cin_ids: set[UUID] = set()
    address_match_ids: set[UUID] = set()
    address_conflict_ids: set[UUID] = set()
    evidence: dict[UUID, EntityCandidateEvidenceSnippetsItem] = {}
    for page in inspection.pages:
        if not page.company_controlled:
            continue
        for disclosure in page.disclosures:
            item = _page_evidence(page, disclosure)
            if disclosure.kind is DisclosureKind.LEGAL_NAME:
                disclosure_name = _normalised_name(disclosure.value)
                if disclosure_name == current_name:
                    exact_name_ids.add(item.evidence_id)
                    legal_page_ids.add(item.evidence_id)
                    evidence[item.evidence_id] = item
                elif disclosure_name in former_names:
                    legal_page_ids.add(item.evidence_id)
                    evidence[item.evidence_id] = item
            elif disclosure.kind is DisclosureKind.CIN and disclosure.value.upper() == record.cin:
                cin_ids.add(item.evidence_id)
                evidence[item.evidence_id] = item
            elif disclosure.kind is DisclosureKind.REGISTERED_OFFICE:
                if _address_matches_master(disclosure.value, record):
                    address_match_ids.add(item.evidence_id)
                    evidence[item.evidence_id] = item
                elif _address_conflicts_with_master_state(disclosure.value, record):
                    address_conflict_ids.add(item.evidence_id)
                    evidence[item.evidence_id] = item
    return _CandidateSiteFacts(
        exact_name_ids=frozenset(exact_name_ids),
        legal_page_ids=frozenset(legal_page_ids),
        cin_ids=frozenset(cin_ids),
        address_match_ids=frozenset(address_match_ids),
        address_conflict_ids=frozenset(address_conflict_ids),
        evidence=tuple(evidence.values()),
    )


ADDRESS_STOP_WORDS: Final = frozenset(
    {
        "address",
        "building",
        "floor",
        "india",
        "limited",
        "no",
        "number",
        "office",
        "plot",
        "registered",
        "road",
        "street",
    }
)
INDIAN_STATES: Final = tuple(
    sorted(
        {
            "andhra pradesh",
            "arunachal pradesh",
            "assam",
            "bihar",
            "chhattisgarh",
            "delhi",
            "goa",
            "gujarat",
            "haryana",
            "himachal pradesh",
            "jammu and kashmir",
            "jharkhand",
            "karnataka",
            "kerala",
            "ladakh",
            "madhya pradesh",
            "maharashtra",
            "manipur",
            "meghalaya",
            "mizoram",
            "nagaland",
            "odisha",
            "puducherry",
            "punjab",
            "rajasthan",
            "tamil nadu",
            "telangana",
            "uttar pradesh",
            "uttarakhand",
            "west bengal",
        },
        key=len,
        reverse=True,
    )
)


def _address_tokens(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if token not in ADDRESS_STOP_WORDS and len(token) > 1
    }


def _address_matches_master(value: str, record: CompanyDataRecord) -> bool:
    summary = record.registered_office_summary
    state = record.registered_office_state
    if summary is None:
        return False
    site_tokens = _address_tokens(value)
    master_tokens = _address_tokens(summary)
    if not site_tokens or not master_tokens:
        return False
    common = site_tokens & master_tokens
    overlap = len(common) / min(len(site_tokens), len(master_tokens))
    state_matches = state is None or state.casefold() in value.casefold()
    return state_matches and len(common) >= 3 and overlap >= 0.5


def _address_conflicts_with_master_state(value: str, record: CompanyDataRecord) -> bool:
    if record.registered_office_state is None:
        return False
    site_state = next((state for state in INDIAN_STATES if state in value.casefold()), None)
    return site_state is not None and site_state != record.registered_office_state.casefold()


def _signal_matches_record(signal: ResolutionSignal, record: CompanyDataRecord) -> bool:
    if signal.candidate_cin is not None:
        return signal.candidate_cin == record.cin
    assert signal.candidate_legal_name is not None
    names = {_normalised_name(record.legal_name), *map(_normalised_name, record.former_names)}
    return _normalised_name(signal.candidate_legal_name) in names


def _factor_evidence(
    site: _CandidateSiteFacts,
    signals: Sequence[ResolutionSignal],
    provider_ids: tuple[UUID, ...],
    facts: ScoringFacts,
) -> Mapping[ScoringFactor, frozenset[UUID]]:
    result: dict[ScoringFactor, set[UUID]] = {
        ScoringFactor.EXACT_LEGAL_NAME_AND_CIN_ON_DOMAIN: set(
            (*site.exact_name_ids, *site.cin_ids)
        ),
        ScoringFactor.ADDRESS_CONTACT_MATCHES_MASTER_DATA: set(
            (*site.address_match_ids, *provider_ids)
        ),
        ScoringFactor.COMPANY_CONTROLLED_LEGAL_PAGE: set(site.legal_page_ids),
        ScoringFactor.CONFLICTING_REGISTERED_OFFICE: set(
            (*site.address_conflict_ids, *provider_ids)
        ),
        ScoringFactor.INACTIVE_STATUS: set(provider_ids),
        ScoringFactor.NAME_ONLY_MATCH: set(provider_ids),
    }
    for signal in signals:
        result.setdefault(SIGNAL_FACTORS[signal.kind], set()).add(signal.evidence.evidence_id)
    return MappingProxyType(
        {
            factor: frozenset(ids) if facts.applies(factor) else frozenset()
            for factor, ids in result.items()
        }
    )


def _dedupe_evidence(
    values: Sequence[EntityCandidateEvidenceSnippetsItem],
) -> tuple[EntityCandidateEvidenceSnippetsItem, ...]:
    result: dict[UUID, EntityCandidateEvidenceSnippetsItem] = {}
    for value in values:
        result[value.evidence_id] = value
    return tuple(result.values())


def _is_listed(record: CompanyDataRecord) -> bool:
    return record.listed is True or record.cin.startswith("L")


def _company_type(record: CompanyDataRecord) -> EntityCandidateCompanyType:
    if _is_listed(record):
        return EntityCandidateCompanyType.LISTED
    company_type = (record.company_type or "").casefold()
    if "private" in company_type or "one person" in company_type:
        return EntityCandidateCompanyType.PRIVATE
    if "public" in company_type:
        return EntityCandidateCompanyType.PUBLIC_UNLISTED
    raise CandidateGenerationError("candidate_company_type_unsupported")


def _primary_domain(inspection: SiteInspection | None) -> str | None:
    if inspection is None:
        return None
    return urlsplit(inspection.root_url).hostname


def _status_is_inactive(status: str | None) -> bool:
    if status is None:
        return False
    value = status.casefold()
    return any(
        marker in value
        for marker in ("inactive", "dissolved", "strike off", "struck off", "liquidat")
    )


def _conflict_messages(facts: ScoringFacts) -> list[str]:
    messages: list[str] = []
    if facts.inactive_status:
        messages.append("Company status appears inactive; confirm any successor or former name.")
    if facts.conflicting_registered_office:
        messages.append("The registered-office evidence conflicts with the master-data record.")
    if facts.incompatible_business_description:
        messages.append("The public business description appears incompatible with this candidate.")
    if facts.name_only_match:
        messages.append("This candidate is linked by name only; add a CIN or stronger evidence.")
    if facts.common_name_adverse_ambiguity:
        messages.append("A common company name creates unresolved adverse-result ambiguity.")
    return messages


def _merge_company_records(
    existing: CompanyDataRecord,
    incoming: CompanyDataRecord,
) -> CompanyDataRecord:
    if existing.cin != incoming.cin:
        raise CandidateGenerationError("candidate_record_identity_mismatch")
    former_names = tuple(dict.fromkeys((*existing.former_names, *incoming.former_names)))
    return CompanyDataRecord(
        cin=existing.cin,
        legal_name=existing.legal_name,
        former_names=former_names,
        company_type=existing.company_type or incoming.company_type,
        status=existing.status or incoming.status,
        active=existing.active if existing.active is not None else incoming.active,
        incorporated_date=existing.incorporated_date or incoming.incorporated_date,
        listed=existing.listed if existing.listed is not None else incoming.listed,
        registered_office_state=(
            existing.registered_office_state or incoming.registered_office_state
        ),
        registered_office_summary=(
            existing.registered_office_summary or incoming.registered_office_summary
        ),
        source_record_id=existing.source_record_id,
    )
