from __future__ import annotations

from pathlib import Path


def replace_once(path: str, old: str, new: str, label: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    file.write_text(text.replace(old, new), encoding="utf-8")
    print(f"updated {label}")


candidates = "services/worker/mandate_worker/entity_resolution/candidates.py"

relationship_model = '''class EntityRelationshipHint(BaseModel):
    """Public-evidence relationship metadata; it never contributes to confidence scoring."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    candidate_cin: str | None = Field(default=None, alias="candidateCin")
    candidate_legal_name: str | None = Field(
        default=None,
        alias="candidateLegalName",
        min_length=1,
        max_length=300,
    )
    brand_names: tuple[str, ...] = Field(default=(), alias="brandNames", max_length=20)
    related_entity_reason: str | None = Field(
        default=None,
        alias="relatedEntityReason",
        max_length=500,
    )
    evidence: EntityCandidateEvidenceSnippetsItem

    @field_validator("candidate_cin", mode="before")
    @classmethod
    def normalise_candidate_cin(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("relationship candidate CIN must be a string")
        normalised = value.strip().upper()
        if CIN_PATTERN.fullmatch(normalised) is None:
            raise ValueError("relationship candidate CIN is invalid")
        return normalised

    @field_validator("candidate_legal_name", "related_entity_reason", mode="before")
    @classmethod
    def normalise_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        if not isinstance(value, str):
            raise ValueError("relationship text must be a string")
        normalised = " ".join(value.split())
        if not normalised:
            raise ValueError("relationship text cannot be empty")
        return normalised

    @field_validator("brand_names", mode="before")
    @classmethod
    def normalise_brand_names(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return ()
        if isinstance(value, str):
            raw_values = (value,)
        elif isinstance(value, list | tuple):
            raw_values = tuple(value)
        else:
            raise ValueError("brand names must be a string or sequence")
        result: list[str] = []
        seen: set[str] = set()
        for raw in raw_values:
            if not isinstance(raw, str):
                raise ValueError("brand name must be a string")
            brand = " ".join(raw.split())
            if not brand or len(brand) > 200:
                raise ValueError("brand name is empty or too long")
            key = brand.casefold()
            if key not in seen:
                seen.add(key)
                result.append(brand)
        return tuple(result)

    @model_validator(mode="after")
    def validate_scope_and_content(self) -> Self:
        if self.candidate_cin is None and self.candidate_legal_name is None:
            raise ValueError("relationship hint must identify a candidate")
        if not self.brand_names and self.related_entity_reason is None:
            raise ValueError("relationship hint must add a brand or material related-entity reason")
        return self


'''
replace_once(
    candidates,
    "class CandidateGeneratorConfig(BaseModel):",
    relationship_model + "class CandidateGeneratorConfig(BaseModel):",
    "relationship hint model",
)

site_facts = '''@dataclass(frozen=True, slots=True)
class _CandidateSiteFacts:
    exact_name_ids: frozenset[UUID]
    legal_page_ids: frozenset[UUID]
    cin_ids: frozenset[UUID]
    address_match_ids: frozenset[UUID]
    address_conflict_ids: frozenset[UUID]
    evidence: tuple[EntityCandidateEvidenceSnippetsItem, ...]
'''
relationship_facts_model = site_facts + '''

@dataclass(frozen=True, slots=True)
class _CandidateRelationshipFacts:
    brand_names: tuple[str, ...]
    related_entity_reason: str | None
    evidence: tuple[EntityCandidateEvidenceSnippetsItem, ...]
'''
replace_once(
    candidates,
    site_facts,
    relationship_facts_model,
    "relationship facts model",
)

replace_once(
    candidates,
    '''        site_inspection: SiteInspection | None = None,
        signals: Sequence[ResolutionSignal] = (),
    ) -> CandidateGenerationResult:
''',
    '''        site_inspection: SiteInspection | None = None,
        signals: Sequence[ResolutionSignal] = (),
        relationship_hints: Sequence[EntityRelationshipHint] = (),
    ) -> CandidateGenerationResult:
''',
    "generator relationship parameter",
)
replace_once(
    candidates,
    '''                site_inspection=site_inspection,
                signals=signals,
            )
''',
    '''                site_inspection=site_inspection,
                signals=signals,
                relationship_hints=relationship_hints,
            )
''',
    "pass relationship hints",
)
replace_once(
    candidates,
    '''        site_inspection: SiteInspection | None,
        signals: Sequence[ResolutionSignal],
    ) -> tuple[EntityCandidate, CandidateScoreAudit]:
''',
    '''        site_inspection: SiteInspection | None,
        signals: Sequence[ResolutionSignal],
        relationship_hints: Sequence[EntityRelationshipHint],
    ) -> tuple[EntityCandidate, CandidateScoreAudit]:
''',
    "score relationship parameter",
)
replace_once(
    candidates,
    '''        matching_signals = tuple(
            signal for signal in signals if _signal_matches_record(signal, record)
        )
        signal_factors = {SIGNAL_FACTORS[signal.kind] for signal in matching_signals}
''',
    '''        matching_signals = tuple(
            signal for signal in signals if _signal_matches_record(signal, record)
        )
        relationship = _relationship_facts(record, relationship_hints)
        signal_factors = {SIGNAL_FACTORS[signal.kind] for signal in matching_signals}
''',
    "resolve relationship facts",
)
replace_once(
    candidates,
    '''        evidence = _dedupe_evidence(
            (*site.evidence, *signal_evidence, *aggregate.provider_evidence.values())
        )[:MAX_EVIDENCE_PER_CANDIDATE]
''',
    '''        evidence = _dedupe_evidence(
            (
                *site.evidence,
                *signal_evidence,
                *relationship.evidence,
                *aggregate.provider_evidence.values(),
            )
        )[:MAX_EVIDENCE_PER_CANDIDATE]
''',
    "include relationship evidence",
)
replace_once(
    candidates,
    '''            primaryDomain=_primary_domain(site_inspection) if site.evidence else None,
            brandNames=[],
            confidenceScore=calculation.score,
''',
    '''            primaryDomain=_primary_domain(site_inspection) if site.evidence else None,
            brandNames=list(relationship.brand_names),
            relatedEntityReason=relationship.related_entity_reason,
            confidenceScore=calculation.score,
''',
    "populate relationship fields",
)

relationship_helpers = '''def _relationship_facts(
    record: CompanyDataRecord,
    hints: Sequence[EntityRelationshipHint],
) -> _CandidateRelationshipFacts:
    matching = tuple(hint for hint in hints if _relationship_matches_record(hint, record))
    brands: list[str] = []
    seen_brands: set[str] = set()
    reasons: dict[str, str] = {}
    evidence: list[EntityCandidateEvidenceSnippetsItem] = []
    for hint in matching:
        for brand in hint.brand_names:
            key = brand.casefold()
            if key not in seen_brands:
                seen_brands.add(key)
                brands.append(brand)
        if hint.related_entity_reason is not None:
            reasons.setdefault(hint.related_entity_reason.casefold(), hint.related_entity_reason)
        evidence.append(hint.evidence)
    if len(reasons) > 1:
        raise CandidateGenerationError("conflicting_entity_relationship_hints")
    return _CandidateRelationshipFacts(
        brand_names=tuple(brands[:20]),
        related_entity_reason=next(iter(reasons.values()), None),
        evidence=_dedupe_evidence(evidence),
    )


def _relationship_matches_record(
    hint: EntityRelationshipHint,
    record: CompanyDataRecord,
) -> bool:
    matched = False
    if hint.candidate_cin is not None:
        if hint.candidate_cin != record.cin:
            return False
        matched = True
    if hint.candidate_legal_name is not None:
        candidate_name = _normalised_name(hint.candidate_legal_name)
        record_names = {
            _normalised_name(record.legal_name),
            *(_normalised_name(name) for name in record.former_names),
        }
        if candidate_name not in record_names:
            return False
        matched = True
    return matched


def brand_context_statement(candidate: EntityCandidate, brand_name: str) -> str:
    """Render the product-spec brand rule without replacing the legal identity."""

    requested = " ".join(brand_name.split())
    canonical = next(
        (brand for brand in candidate.brand_names if brand.casefold() == requested.casefold()),
        None,
    )
    if canonical is None:
        raise ValueError("brand is not attached to the legal-entity candidate")
    return f"{candidate.legal_name} operates the {canonical} business/website."


'''
replace_once(
    candidates,
    "def _candidate_names(\n",
    relationship_helpers + "def _candidate_names(\n",
    "relationship helper functions",
)

init_file = "services/worker/mandate_worker/entity_resolution/__init__.py"
replace_once(
    init_file,
    '''    CandidateSignalKind,
    EntityCandidateGenerator,
''',
    '''    CandidateSignalKind,
    EntityCandidateGenerator,
    EntityRelationshipHint,
''',
    "relationship hint import",
)
replace_once(
    init_file,
    '''    ScoringFacts,
    confidence_label,
''',
    '''    ScoringFacts,
    brand_context_statement,
    confidence_label,
''',
    "brand helper import",
)
replace_once(
    init_file,
    '''    "EntityCandidateGenerator",
''',
    '''    "EntityCandidateGenerator",
    "EntityRelationshipHint",
''',
    "relationship hint __all__",
)
replace_once(
    init_file,
    '''    "build_entity_resolution_task_loop",
''',
    '''    "brand_context_statement",
    "build_entity_resolution_task_loop",
''',
    "brand helper __all__",
)
