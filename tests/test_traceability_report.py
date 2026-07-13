from __future__ import annotations

from pathlib import Path

import pytest

from scripts.generate_traceability_report import (
    TraceabilityError,
    build_report,
    parse_junit,
    parse_matrix,
    validate_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "docs" / "implementation" / "REQUIREMENTS-TRACEABILITY.md"


def write_junit(path: Path, testcase: str, outcome: str | None = None) -> Path:
    child = f"<{outcome} />" if outcome is not None else ""
    path.write_text(
        f'<testsuite tests="1"><testcase classname="acceptance" name="{testcase}">'
        f"{child}</testcase></testsuite>\n",
        encoding="utf-8",
    )
    return path


def test_NFR_03_stage_7_matrix_is_complete_and_has_one_verified_requirement() -> None:
    requirements = parse_matrix(MATRIX)

    assert len(requirements) == 85
    assert requirements["NFR-03"].status == "Verified"
    assert requirements["NFR-03"].acceptance_tag == "AT-NFR-03"


def test_NFR_03_stage_7_report_accepts_passing_underscore_tag(tmp_path: Path) -> None:
    junit = write_junit(tmp_path / "pytest.xml", "test_AT_NFR_03_container_portability")

    report = build_report(MATRIX, [junit])

    assert "| Requirements | 85 |" in report
    assert "| Verified | 1 |" in report
    assert "| NFR-03 | AT-NFR-03 |" in report


def test_NFR_03_stage_7_rejects_unknown_acceptance_tag(tmp_path: Path) -> None:
    junit = write_junit(tmp_path / "pytest.xml", "test_AT_UNKNOWN_99_typo")
    requirements = parse_matrix(MATRIX)
    evidence = parse_junit([junit])

    with pytest.raises(TraceabilityError, match="unknown acceptance tag AT-UNKNOWN-99"):
        validate_evidence(requirements, evidence)


@pytest.mark.parametrize("outcome", ["failure", "error", "skipped"])
def test_NFR_03_stage_7_verified_requirement_requires_passing_test(
    tmp_path: Path,
    outcome: str,
) -> None:
    junit = write_junit(tmp_path / "pytest.xml", "test_AT_NFR_03_portability", outcome)
    requirements = parse_matrix(MATRIX)
    evidence = parse_junit([junit])

    with pytest.raises(TraceabilityError, match="NFR-03 has no passing AT-NFR-03"):
        validate_evidence(requirements, evidence)
