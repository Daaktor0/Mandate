from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPONENT = ROOT / "apps" / "web" / "components" / "entity-confirmation-view.tsx"


def _component() -> str:
    return COMPONENT.read_text(encoding="utf-8")


def test_ENTITY_03_candidate_cards_show_identity_evidence_and_confidence() -> None:
    source = _component()

    for field in (
        "candidate.legalName",
        "candidate.cin",
        "candidate.status",
        "candidate.registeredOfficeSummary",
        "candidate.primaryDomain",
        "candidate.evidenceSnippets",
        "candidate.confidenceLabel",
        "candidate.conflicts",
    ):
        assert field in source
    assert 'name="primary-entity"' in source
    assert "checked={selectedCandidateId === candidate.candidateId}" in source
    assert "setSelectedCandidateId(null)" in source


def test_ENTITY_04_confirmation_ui_supports_none_and_public_identity_refinement() -> None:
    source = _component()
    compact_source = " ".join(source.split())

    assert "None of these" in source
    assert 'action: "none_of_these"' in source
    assert "Enter legal name or add CIN" in source
    assert 'action: "refine"' in source
    assert "Do not enter mandate" in compact_source
    assert "description" not in source
    assert "upload" not in source.lower()


def test_ENTITY_07_related_scope_is_optional_and_capped_at_two() -> None:
    source = _component()

    assert "Clarify multiple entities" in source
    assert "candidate.relatedEntityReason" in source
    assert "current.length >= 2" in source
    assert "at most two material related entities" in source


def test_INTAKE_06_confirmation_discloses_no_entitlement_reservation() -> None:
    source = _component()

    assert "No entitlement is reserved here." in source
    assert "explicit confirmation" in source
    assert "reserveEntitlement" not in source
