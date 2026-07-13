"""Validate requirement/test linkage and emit the TEST-PLAN stage 7 report."""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

REQUIREMENT_ID = re.compile(r"^(?P<id>[A-Z][A-Z0-9]*-[0-9]{2})(?:\s|$)")
MATRIX_ACCEPTANCE_TAG = re.compile(r"\bAT-(?P<id>[A-Z][A-Z0-9]*-[0-9]{2})\b")
TEST_ACCEPTANCE_TAG = re.compile(
    r"(?<![A-Z0-9])AT[-_](?P<prefix>[A-Z][A-Z0-9]*)[-_](?P<number>[0-9]{2})(?![A-Z0-9])",
    re.IGNORECASE,
)
ALLOWED_STATUSES = {"Specified", "In progress", "Implemented", "Verified", "Blocked"}


class TraceabilityError(ValueError):
    """The traceability matrix or its passing-test evidence is inconsistent."""


@dataclass(frozen=True, slots=True)
class Requirement:
    requirement_id: str
    summary: str
    acceptance: str
    status: str

    @property
    def acceptance_tag(self) -> str:
        return f"AT-{self.requirement_id}"


@dataclass(frozen=True, slots=True)
class TestEvidence:
    label: str
    acceptance_tags: frozenset[str]
    passed: bool


def parse_matrix(path: Path) -> dict[str, Requirement]:
    requirements: dict[str, Requirement] = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) != 7:
            continue
        match = REQUIREMENT_ID.match(cells[0])
        if match is None:
            continue

        requirement_id = match.group("id")
        if requirement_id in requirements:
            raise TraceabilityError(
                f"duplicate requirement {requirement_id} at matrix line {line_number}"
            )
        status = cells[6]
        if status not in ALLOWED_STATUSES:
            raise TraceabilityError(
                f"unknown status {status!r} for {requirement_id} at matrix line {line_number}"
            )
        requirement = Requirement(
            requirement_id=requirement_id,
            summary=cells[1],
            acceptance=cells[4],
            status=status,
        )
        if requirement.requirement_id not in MATRIX_ACCEPTANCE_TAG.findall(requirement.acceptance):
            raise TraceabilityError(
                f"{requirement_id} does not reference its dedicated "
                f"{requirement.acceptance_tag} acceptance tag"
            )
        requirements[requirement_id] = requirement

    if not requirements:
        raise TraceabilityError("traceability matrix contains no requirement rows")

    known_ids = set(requirements)
    for requirement in requirements.values():
        for tagged_id in MATRIX_ACCEPTANCE_TAG.findall(requirement.acceptance):
            if tagged_id not in known_ids:
                raise TraceabilityError(
                    f"matrix acceptance tag AT-{tagged_id} references an unknown requirement"
                )
    return requirements


def _local_name(tag: str) -> str:
    return tag.rsplit("}", maxsplit=1)[-1]


def _acceptance_tags(value: str) -> frozenset[str]:
    return frozenset(
        f"AT-{match.group('prefix').upper()}-{match.group('number')}"
        for match in TEST_ACCEPTANCE_TAG.finditer(value)
    )


def parse_junit(paths: Sequence[Path]) -> tuple[TestEvidence, ...]:
    if not paths:
        raise TraceabilityError("at least one JUnit report is required")

    evidence: list[TestEvidence] = []
    for path in paths:
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError) as error:
            raise TraceabilityError(f"cannot read JUnit report {path}") from error
        for testcase in root.iter():
            if _local_name(testcase.tag) != "testcase":
                continue
            attributes = testcase.attrib
            label_parts = [
                value
                for value in (
                    attributes.get("classname"),
                    attributes.get("name"),
                    attributes.get("file"),
                )
                if value
            ]
            label = " :: ".join(label_parts) or f"unnamed testcase in {path.name}"
            outcome_tags = {_local_name(child.tag) for child in testcase}
            evidence.append(
                TestEvidence(
                    label=label,
                    acceptance_tags=_acceptance_tags(label),
                    passed=not outcome_tags.intersection({"failure", "error", "skipped"}),
                )
            )

    if not evidence:
        raise TraceabilityError("JUnit reports contain no test cases")
    return tuple(evidence)


def validate_evidence(
    requirements: dict[str, Requirement],
    evidence: Iterable[TestEvidence],
) -> dict[str, tuple[str, ...]]:
    known_tags = {requirement.acceptance_tag for requirement in requirements.values()}
    passing_labels: dict[str, set[str]] = defaultdict(set)

    for test in evidence:
        for tag in test.acceptance_tags:
            if tag not in known_tags:
                raise TraceabilityError(
                    f"test {test.label!r} references unknown acceptance tag {tag}"
                )
            if test.passed:
                passing_labels[tag].add(test.label)

    for requirement in requirements.values():
        if requirement.status == "Verified" and not passing_labels[requirement.acceptance_tag]:
            raise TraceabilityError(
                f"verified requirement {requirement.requirement_id} has no passing "
                f"{requirement.acceptance_tag} test"
            )

    return {tag: tuple(sorted(labels)) for tag, labels in sorted(passing_labels.items()) if labels}


def _markdown(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_report(
    requirements: dict[str, Requirement],
    evidence: Sequence[TestEvidence],
    passing_labels: dict[str, tuple[str, ...]],
) -> str:
    status_counts = Counter(requirement.status for requirement in requirements.values())
    verified = sorted(
        (requirement for requirement in requirements.values() if requirement.status == "Verified"),
        key=lambda requirement: requirement.requirement_id,
    )
    tagged_tests = sum(1 for test in evidence if test.acceptance_tags)

    lines = [
        "# Requirements traceability report",
        "",
        "Generated deterministically from `REQUIREMENTS-TRACEABILITY.md` "
        "and passing JUnit evidence.",
        "",
        "## Summary",
        "",
        "| Measure | Count |",
        "|---|---:|",
        f"| Requirements | {len(requirements)} |",
        f"| Specified | {status_counts['Specified']} |",
        f"| In progress | {status_counts['In progress']} |",
        f"| Implemented | {status_counts['Implemented']} |",
        f"| Verified | {status_counts['Verified']} |",
        f"| Blocked | {status_counts['Blocked']} |",
        f"| JUnit test cases | {len(evidence)} |",
        f"| Acceptance-tagged test cases | {tagged_tests} |",
        "",
        "## Verified requirements",
        "",
        "| Requirement | Acceptance tag | Passing evidence |",
        "|---|---|---|",
    ]
    for requirement in verified:
        labels = passing_labels[requirement.acceptance_tag]
        lines.append(
            f"| {requirement.requirement_id} | {requirement.acceptance_tag} | "
            f"{_markdown('; '.join(labels))} |"
        )
    if not verified:
        lines.append("| — | — | No requirements are marked Verified |")

    lines.extend(
        [
            "",
            "## Passing acceptance tags",
            "",
            "| Acceptance tag | Passing test cases |",
            "|---|---:|",
        ]
    )
    for tag, labels in passing_labels.items():
        lines.append(f"| {tag} | {len(labels)} |")
    if not passing_labels:
        lines.append("| — | 0 |")
    lines.append("")
    return "\n".join(lines)


def build_report(matrix: Path, junit_paths: Sequence[Path]) -> str:
    requirements = parse_matrix(matrix)
    evidence = parse_junit(junit_paths)
    passing_labels = validate_evidence(requirements, evidence)
    return render_report(requirements, evidence, passing_labels)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, required=True)
    parser.add_argument("--junit", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = build_report(args.matrix, args.junit)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    except TraceabilityError as error:
        print(f"traceability error: {error}", file=sys.stderr)
        return 1
    print(f"traceability report written to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
