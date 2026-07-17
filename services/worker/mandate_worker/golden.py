"""Strict loader for the deterministic GC-01..15 evaluation corpus."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Final, cast
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

GOLDEN_CASE_COUNT: Final = 15
MAX_GOLDEN_CASE_BYTES: Final = 64 * 1024
DEFAULT_GOLDEN_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "golden"
_FORBIDDEN_KEYS: Final = frozenset(
    {
        "accountid",
        "apikey",
        "authorization",
        "billing",
        "cookie",
        "confidential",
        "email",
        "emailaddress",
        "firm",
        "letterhead",
        "matternarrative",
        "oauth_token",
        "oauth_token_value",
        "password",
        "prompt",
        "prompt_text",
        "phone",
        "rawbody",
        "rawhtml",
        "rawsource",
        "rawtext",
        "secret",
        "source_text",
        "userid",
        "useremail",
    }
)
_NORMALISED_FORBIDDEN_KEYS: Final = frozenset(
    item.casefold().replace("-", "").replace("_", "") for item in _FORBIDDEN_KEYS
)


class GoldenFixtureError(RuntimeError):
    """The golden corpus is missing, malformed, unsafe, or incomplete."""


class GoldenEntity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    legal_name: str = Field(alias="legalName", min_length=3, max_length=160)
    entity_type: str = Field(alias="entityType", min_length=2, max_length=40)
    jurisdiction: str = Field(pattern=r"^[A-Z]{2}$")
    identifiers: tuple[str, ...] = Field(min_length=1, max_length=4)


class GoldenExpectations(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    correct_entity: GoldenEntity = Field(alias="correctEntity")
    must_find_facts: tuple[str, ...] = Field(alias="mustFindFacts", min_length=1, max_length=12)
    regulatory_touchpoints: tuple[str, ...] = Field(alias="regulatoryTouchpoints", max_length=10)
    unacceptable_claims: tuple[str, ...] = Field(
        alias="unacceptableClaims", min_length=1, max_length=12
    )
    must_ask_questions: tuple[str, ...] = Field(
        alias="mustAskQuestions", min_length=1, max_length=12
    )
    source_expectations: tuple[str, ...] = Field(
        alias="sourceExpectations", min_length=1, max_length=12
    )
    quality_gates: tuple[str, ...] = Field(alias="qualityGates", min_length=1, max_length=12)


class GoldenCase(BaseModel):
    """Inputs and expected machine-checkable outcomes for one golden case."""

    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    case_id: str = Field(alias="caseId", pattern=r"^GC-(0[1-9]|1[0-5])$")
    title: str = Field(min_length=3, max_length=120)
    category: str = Field(min_length=3, max_length=80)
    inputs: dict[str, object] = Field(min_length=1, alias="inputs")
    expectations: GoldenExpectations

    @field_validator("inputs")
    @classmethod
    def inputs_have_required_shape(cls, value: dict[str, object]) -> dict[str, object]:
        required = {"submittedUrl", "asOf", "entityHint", "focusTopics"}
        if not required.issubset(value):
            missing = ", ".join(sorted(required - value.keys()))
            raise ValueError(f"golden inputs missing required keys: {missing}")
        if not isinstance(value["submittedUrl"], str):
            raise ValueError("golden submittedUrl must be a string")
        if not isinstance(value["asOf"], str):
            raise ValueError("golden asOf must be a string")
        try:
            date.fromisoformat(value["asOf"])
        except ValueError as error:
            raise ValueError("golden asOf must be an ISO date") from error
        if not isinstance(value["entityHint"], dict):
            raise ValueError("golden entityHint must be an object")
        if not isinstance(value["focusTopics"], list) or not value["focusTopics"]:
            raise ValueError("golden focusTopics must be a non-empty list")
        return value


def _normalise_key(key: object) -> str:
    return str(key).casefold().replace("-", "").replace("_", "")


def _validate_safe_values(value: object, *, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalised = _normalise_key(key)
            if normalised in _NORMALISED_FORBIDDEN_KEYS:
                raise GoldenFixtureError(f"forbidden golden field: {path}.{key}")
            _validate_safe_values(child, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _validate_safe_values(child, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        hostname = (urlparse(value).hostname or "").casefold()
        if not (
            hostname == "example"
            or hostname.endswith(".example")
            or hostname == "example.com"
            or hostname.endswith(".example.com")
        ):
            raise GoldenFixtureError(f"golden URL must use a reserved example host: {path}")


def _read_case(path: Path) -> GoldenCase:
    try:
        raw = path.read_bytes()
        if len(raw) > MAX_GOLDEN_CASE_BYTES:
            raise GoldenFixtureError(f"golden case exceeds size limit: {path.name}")
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise GoldenFixtureError(f"golden case must be an object: {path.name}")
        _validate_safe_values(parsed)
        case = GoldenCase.model_validate(cast(dict[str, object], parsed))
    except GoldenFixtureError:
        raise
    except (OSError, json.JSONDecodeError, ValidationError, ValueError) as error:
        raise GoldenFixtureError(f"golden case validation failed: {path.name}") from error
    if case.case_id != path.stem:
        raise GoldenFixtureError(f"golden filename and caseId differ: {path.name}")
    return case


def load_golden_cases(root: Path | None = None) -> tuple[GoldenCase, ...]:
    """Load exactly the versioned GC-01..15 corpus in deterministic order."""

    try:
        fixture_root = (root or DEFAULT_GOLDEN_ROOT).resolve(strict=True)
    except OSError as error:
        raise GoldenFixtureError("golden fixture root is unavailable") from error
    paths = sorted(fixture_root.glob("GC-*.json"))
    expected = {f"GC-{index:02d}" for index in range(1, GOLDEN_CASE_COUNT + 1)}
    actual = {path.stem for path in paths}
    if len(paths) != GOLDEN_CASE_COUNT or actual != expected:
        raise GoldenFixtureError("golden corpus must contain exactly GC-01 through GC-15")
    cases = tuple(_read_case(path) for path in paths)
    if len({case.case_id for case in cases}) != GOLDEN_CASE_COUNT:
        raise GoldenFixtureError("golden case IDs must be unique")
    return cases
