from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

import pytest
from mandate_worker.entity_resolution import (
    EntityCandidateGenerator,
    EntityRelationshipHint,
    LegalPageCrawler,
    LimitationCode,
    ResolutionGuidanceCode,
    ResolutionSignal,
    brand_context_statement,
)
from mandate_worker.fetch import SafeFetchError, SafeFetchResult
from mandate_worker.providers.company_data import (
    CompanyDataOperation,
    CompanyDataRecord,
    CompanyDataResponse,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

ROOT = Path(__file__).resolve().parents[3]
FIXTURE_FILE = ROOT / "fixtures" / "entity-resolution" / "cases.json"
PUBLIC_IP = "93.184.216.34"
REQUIRED_CASE_IDS = tuple(f"ER-{index:02d}" for index in range(1, 12))


class FetchOutcomeFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    url: str = Field(min_length=1, max_length=2048)
    body: str | None = None
    content_type: str | None = Field(default=None, alias="contentType", max_length=200)
    status_code: int | None = Field(default=None, alias="statusCode", ge=100, le=599)
    error_code: str | None = Field(default=None, alias="errorCode", max_length=100)
    retryable: bool = False

    @model_validator(mode="after")
    def exactly_one_success_or_error(self) -> Self:
        success = self.body is not None
        failure = self.error_code is not None
        if success == failure:
            raise ValueError("fetch fixture must define exactly one body or errorCode")
        if success and (self.content_type is None or self.status_code is None):
            raise ValueError("successful fetch fixture requires contentType and statusCode")
        if failure and (self.content_type is not None or self.status_code is not None):
            raise ValueError("failed fetch fixture cannot define response metadata")
        return self


class ExpectedFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    candidate_cins: tuple[str, ...] = Field(alias="candidateCins")
    primary_candidate_cin: str | None = Field(default=None, alias="primaryCandidateCin")
    labels: dict[str, str] = Field(default_factory=dict)
    legal_names: dict[str, str] = Field(default_factory=dict, alias="legalNames")
    former_names: dict[str, tuple[str, ...]] = Field(default_factory=dict, alias="formerNames")
    brand_names: dict[str, tuple[str, ...]] = Field(default_factory=dict, alias="brandNames")
    brand_context_statements: dict[str, str] = Field(
        default_factory=dict,
        alias="brandContextStatements",
    )
    related_entity_reasons: dict[str, str] = Field(
        default_factory=dict,
        alias="relatedEntityReasons",
    )
    conflict_contains: dict[str, tuple[str, ...]] = Field(
        default_factory=dict,
        alias="conflictContains",
    )
    company_controlled_evidence: tuple[str, ...] = Field(
        default=(),
        alias="companyControlledEvidence",
    )
    excluded_legal_names: tuple[str, ...] = Field(default=(), alias="excludedLegalNames")
    limitation_codes: tuple[str, ...] = Field(default=(), alias="limitationCodes")
    limitation_detail_codes: tuple[str, ...] = Field(
        default=(),
        alias="limitationDetailCodes",
    )
    prompt_injection_suspected: bool = Field(
        default=False,
        alias="promptInjectionSuspected",
    )
    requires_user_confirmation: bool = Field(alias="requiresUserConfirmation")
    needs_identity_input: bool = Field(alias="needsIdentityInput")
    guidance_code: str | None = Field(default=None, alias="guidanceCode")
    abandoned_outcome: str | None = Field(default=None, alias="abandonedOutcome")


class EntityResolutionFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    case_id: str = Field(alias="id", pattern=r"^ER-(0[1-9]|1[01])$")
    title: str = Field(min_length=1, max_length=200)
    root_url: str = Field(alias="rootUrl", min_length=1, max_length=2048)
    responses: tuple[FetchOutcomeFixture, ...] = Field(min_length=2, max_length=20)
    records: tuple[CompanyDataRecord, ...] = Field(max_length=20)
    searches: dict[str, tuple[str, ...]]
    lookups: dict[str, str]
    signals: tuple[ResolutionSignal, ...] = Field(max_length=30)
    relationships: tuple[EntityRelationshipHint, ...] = Field(max_length=20)
    expected: ExpectedFixture

    @model_validator(mode="after")
    def references_are_closed_and_public(self) -> Self:
        records = {record.cin for record in self.records}
        referenced = (
            {cin for cins in self.searches.values() for cin in cins}
            | set(self.lookups)
            | set(self.lookups.values())
        )
        if not referenced <= records:
            raise ValueError("fixture search/lookup references an unknown company record")
        response_urls = [item.url for item in self.responses]
        if len(response_urls) != len(set(response_urls)):
            raise ValueError("fixture response URLs must be unique")
        if f"{self.root_url}robots.txt" not in response_urls or self.root_url not in response_urls:
            raise ValueError("fixture must include robots.txt and root responses")
        return self


class FixtureEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    fixture_version: int = Field(alias="fixtureVersion", ge=1, le=1)
    notice: str = Field(min_length=1, max_length=200)
    cases: tuple[EntityResolutionFixture, ...] = Field(min_length=11, max_length=11)

    @model_validator(mode="after")
    def complete_acceptance_set(self) -> Self:
        case_ids = tuple(item.case_id for item in self.cases)
        if case_ids != REQUIRED_CASE_IDS:
            raise ValueError("ER fixtures must contain ER-01 through ER-11 in order")
        return self


def _load_fixtures() -> tuple[EntityResolutionFixture, ...]:
    envelope = FixtureEnvelope.model_validate_json(FIXTURE_FILE.read_text(encoding="utf-8"))
    assert (
        envelope.notice
        == "Synthetic public-information fixtures; not MCA or legal-database results."
    )
    return envelope.cases


FIXTURES = _load_fixtures()


def _name_key(value: str) -> str:
    normalised = value.casefold()
    normalised = re.sub(r"\bpvt\.?\b", "private", normalised)
    normalised = re.sub(r"\bltd\.?\b", "limited", normalised)
    return re.sub(r"[^a-z0-9]+", " ", normalised).strip()


@dataclass
class CaseCompanyProvider:
    case: EntityResolutionFixture
    calls: list[tuple[CompanyDataOperation, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._records = {record.cin: record for record in self.case.records}
        self._searches = {
            _name_key(name): tuple(self._records[cin] for cin in cins)
            for name, cins in self.case.searches.items()
        }

    async def search_by_name(self, legal_name: str, *, limit: int = 10) -> CompanyDataResponse:
        self.calls.append((CompanyDataOperation.SEARCH_BY_NAME, legal_name))
        return CompanyDataResponse(
            operation=CompanyDataOperation.SEARCH_BY_NAME,
            public_query=legal_name,
            provider="fixture",
            fixture=True,
            provider_calls=0,
            records=self._searches.get(_name_key(legal_name), ())[:limit],
        )

    async def lookup_by_cin(self, cin: str) -> CompanyDataResponse:
        self.calls.append((CompanyDataOperation.LOOKUP_BY_CIN, cin))
        record = self._records.get(cin)
        return CompanyDataResponse(
            operation=CompanyDataOperation.LOOKUP_BY_CIN,
            public_query=cin,
            provider="fixture",
            fixture=True,
            provider_calls=0,
            records=() if record is None else (record,),
        )


@dataclass
class CaseFetcher:
    case: EntityResolutionFixture
    calls: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._outcomes = {item.url: item for item in self.case.responses}

    async def fetch(self, url: str) -> SafeFetchResult:
        self.calls.append(url)
        outcome = self._outcomes.get(url)
        if outcome is None:
            raise AssertionError(f"{self.case.case_id}: unexpected fetch {url}")
        if outcome.error_code is not None:
            raise SafeFetchError(outcome.error_code, retryable=outcome.retryable)
        assert outcome.body is not None
        assert outcome.status_code is not None
        assert outcome.content_type is not None
        return SafeFetchResult(
            requested_url=url,
            final_url=url,
            status_code=outcome.status_code,
            content_type=outcome.content_type,
            body=outcome.body.encode(),
            redirect_chain=(),
            resolved_ip=PUBLIC_IP,
        )


async def _no_sleep(_seconds: float) -> None:
    return None


def _candidate_map(result: Any) -> dict[str, Any]:
    return {
        candidate.cin: candidate for candidate in result.candidates if candidate.cin is not None
    }


def _assert_expected_case(
    case: EntityResolutionFixture,
    inspection: Any,
    result: Any,
) -> None:
    expected = case.expected
    candidate_map = _candidate_map(result)

    assert set(candidate_map) == set(expected.candidate_cins)
    assert result.requires_user_confirmation is expected.requires_user_confirmation
    assert result.needs_identity_input is expected.needs_identity_input
    assert "autoSelectedCandidateId" not in result.model_dump(mode="json", by_alias=True)

    if expected.primary_candidate_cin is not None:
        assert result.candidates[0].cin == expected.primary_candidate_cin
    if expected.guidance_code is not None:
        assert result.guidance_code.value == expected.guidance_code

    for cin, label in expected.labels.items():
        assert candidate_map[cin].confidence_label.value == label
    for cin, legal_name in expected.legal_names.items():
        assert candidate_map[cin].legal_name == legal_name
    for cin, former_names in expected.former_names.items():
        assert tuple(candidate_map[cin].former_names) == former_names
    for cin, brand_names in expected.brand_names.items():
        assert tuple(candidate_map[cin].brand_names) == brand_names
    for cin, statement in expected.brand_context_statements.items():
        brand = expected.brand_names[cin][0]
        assert brand_context_statement(candidate_map[cin], brand) == statement
    for cin, reason in expected.related_entity_reasons.items():
        assert candidate_map[cin].related_entity_reason == reason
    for cin, fragments in expected.conflict_contains.items():
        combined = " ".join(candidate_map[cin].conflicts).casefold()
        assert all(fragment.casefold() in combined for fragment in fragments)
    for cin in expected.company_controlled_evidence:
        assert any(item.company_controlled for item in candidate_map[cin].evidence_snippets)

    legal_names = {candidate.legal_name.casefold() for candidate in result.candidates}
    for excluded in expected.excluded_legal_names:
        assert excluded.casefold() not in legal_names

    assert any(page.prompt_injection_suspected for page in inspection.pages) is (
        expected.prompt_injection_suspected
    )
    limitation_codes = {item.code.value for item in inspection.limitations}
    assert set(expected.limitation_codes) <= limitation_codes
    detail_codes = {
        item.detail_code for item in inspection.limitations if item.detail_code is not None
    }
    assert set(expected.limitation_detail_codes) <= detail_codes

    if expected.abandoned_outcome is not None:
        assert expected.abandoned_outcome == "failed_no_charge"
        assert result.candidates == ()
        assert result.guidance_code is ResolutionGuidanceCode.LEGAL_NAME_OR_CIN_REQUIRED


@pytest.mark.asyncio
@pytest.mark.parametrize("case", FIXTURES, ids=lambda item: item.case_id)
async def test_ER_01_through_ER_11_acceptance_fixtures(case: EntityResolutionFixture) -> None:
    fetcher = CaseFetcher(case)
    inspection = await LegalPageCrawler(fetcher, sleeper=_no_sleep).inspect(case.root_url)
    provider = CaseCompanyProvider(case)
    generator = EntityCandidateGenerator(provider)

    result = await generator.generate(
        report_request_id=__import__("uuid").UUID(
            f"11111111-1111-4111-8111-{int(case.case_id[-2:]):012d}",
        ),
        site_inspection=inspection,
        signals=case.signals,
        relationship_hints=case.relationships,
    )

    _assert_expected_case(case, inspection, result)

    if case.relationships:
        baseline = await EntityCandidateGenerator(CaseCompanyProvider(case)).generate(
            report_request_id=__import__("uuid").UUID(
                f"11111111-1111-4111-8111-{int(case.case_id[-2:]):012d}",
            ),
            site_inspection=inspection,
            signals=case.signals,
        )
        assert [candidate.candidate_id for candidate in result.candidates] == [
            candidate.candidate_id for candidate in baseline.candidates
        ]
        assert [candidate.confidence_score for candidate in result.candidates] == [
            candidate.confidence_score for candidate in baseline.candidates
        ]


def test_ER_fixture_corpus_contains_no_confidential_or_live_credentials() -> None:
    raw = json.loads(FIXTURE_FILE.read_text(encoding="utf-8"))
    serialised = json.dumps(raw).casefold()

    for forbidden in (
        "service_role",
        "supabase_service",
        "authorization",
        "password",
        "transaction details",
        "mandate facts",
        "closingroom",
    ):
        assert forbidden not in serialised
    assert all(".example" in response.url for case in FIXTURES for response in case.responses)
    assert all(
        signal.evidence.source_url.host in {"official.example", "relationship.example"}
        for case in FIXTURES
        for signal in (*case.signals, *case.relationships)
    )


def test_ER_fixture_harness_exercises_private_redirect_limitation() -> None:
    case = next(item for item in FIXTURES if item.case_id == "ER-11")
    failed = next(item for item in case.responses if item.error_code is not None)

    assert failed.error_code == "non_public_ip_address"
    assert LimitationCode.FETCH_FAILED.value in case.expected.limitation_codes
