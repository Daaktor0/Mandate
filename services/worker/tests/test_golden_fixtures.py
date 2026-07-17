from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from mandate_worker.golden import GoldenFixtureError, load_golden_cases

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
GOLDEN_ROOT = REPOSITORY_ROOT / "fixtures" / "golden"
EXPECTED_CASES = {
    "GC-01": "Simple software startup",
    "GC-02": "Manufacturer with factory footprint",
    "GC-03": "Regulated fintech",
    "GC-04": "Health/pharma company",
    "GC-05": "Consumer/food company",
    "GC-06": "SaaS/data company",
    "GC-07": "Public unlisted group",
    "GC-08": "Listed company",
    "GC-09": "Brand/legal-entity mismatch",
    "GC-10": "Cross-border investor context",
    "GC-11": "Sparse private company",
    "GC-12": "Common-name adverse-media false positive",
    "GC-13": "Renamed company",
    "GC-14": "Multi-entity operation",
    "GC-15": "Listed parent / private subsidiary",
}


def test_REPORT_06_GC_01_15_load_complete_typed_corpus() -> None:
    cases = load_golden_cases(GOLDEN_ROOT)

    assert [case.case_id for case in cases] == sorted(EXPECTED_CASES)
    assert {case.title for case in cases} == set(EXPECTED_CASES.values())
    assert all(case.inputs["submittedUrl"].__class__ is str for case in cases)
    assert all(case.expectations.correct_entity.identifiers for case in cases)
    assert all(case.expectations.must_find_facts for case in cases)
    assert all(case.expectations.source_expectations for case in cases)


def test_REPORT_06_GC_12_wrong_entity_is_release_blocking_expectation() -> None:
    case = next(case for case in load_golden_cases(GOLDEN_ROOT) if case.case_id == "GC-12")

    assert "wrong_entity_adverse_media" in case.expectations.quality_gates
    assert "adverse_media_from_common_name_must_not_be_attributed" in (
        case.expectations.unacceptable_claims
    )


def test_REPORT_06_GC_15_injection_page_is_data_not_instruction() -> None:
    case = next(case for case in load_golden_cases(GOLDEN_ROOT) if case.case_id == "GC-15")

    source_signals = case.inputs["sourceSignals"]
    assert isinstance(source_signals, list)
    assert "promptInjectionSuspected" in source_signals
    assert "ignore_untrusted_page_instructions" in case.expectations.quality_gates


def test_REPORT_06_golden_loader_rejects_missing_case(tmp_path: Path) -> None:
    root = tmp_path / "golden"
    shutil.copytree(GOLDEN_ROOT, root)
    (root / "GC-15.json").unlink()

    with pytest.raises(GoldenFixtureError, match="exactly GC-01 through GC-15"):
        load_golden_cases(root)


@pytest.mark.parametrize(
    ("field", "value"),
    [("apiKey", "must-not-exist"), ("rawBody", "must-not-exist")],
)
def test_REPORT_06_golden_loader_rejects_sensitive_or_raw_fields(
    tmp_path: Path, field: str, value: str
) -> None:
    root = tmp_path / "golden"
    shutil.copytree(GOLDEN_ROOT, root)
    path = root / "GC-01.json"
    payload = json.loads(path.read_text())
    assert isinstance(payload, dict)
    payload["inputs"][field] = value
    path.write_text(json.dumps(payload))

    with pytest.raises(GoldenFixtureError, match="forbidden golden field"):
        load_golden_cases(root)


def test_REPORT_06_golden_loader_rejects_non_reserved_url(tmp_path: Path) -> None:
    root = tmp_path / "golden"
    shutil.copytree(GOLDEN_ROOT, root)
    path = root / "GC-01.json"
    payload = json.loads(path.read_text())
    assert isinstance(payload, dict)
    payload["inputs"]["submittedUrl"] = "https://real-company.invalid/about"
    path.write_text(json.dumps(payload))

    with pytest.raises(GoldenFixtureError, match="reserved example host"):
        load_golden_cases(root)
