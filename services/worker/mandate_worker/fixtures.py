"""Validated, deterministic fixture catalog for zero-spend demo mode."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Final, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator


class AdapterCapability(StrEnum):
    SEARCH = "search"
    PAGE_FETCHER = "page_fetcher"
    COMPANY_DATA = "company_data"
    CORPORATE_FILINGS = "corporate_filings"
    REGULATORY = "regulatory"
    LITIGATION = "litigation"
    MODEL = "model"
    QUEUE = "queue"
    STORAGE = "storage"
    EMAIL = "email"


DEMO_BACKENDS: Final[Mapping[AdapterCapability, str]] = MappingProxyType(
    {
        AdapterCapability.SEARCH: "fixture",
        AdapterCapability.PAGE_FETCHER: "fixture",
        AdapterCapability.COMPANY_DATA: "fixture",
        AdapterCapability.CORPORATE_FILINGS: "fixture",
        AdapterCapability.REGULATORY: "fixture",
        AdapterCapability.LITIGATION: "fixture",
        AdapterCapability.MODEL: "fixture",
        AdapterCapability.QUEUE: "memory",
        AdapterCapability.STORAGE: "fixture",
        AdapterCapability.EMAIL: "console",
    }
)

DEFAULT_FIXTURE_ROOT = Path(__file__).resolve().parents[3] / "fixtures" / "demo"


class FixtureCatalogError(RuntimeError):
    """The fixture catalog is absent, malformed, incomplete, or has drifted."""


class FixtureRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    fixture_id: str = Field(alias="id", pattern=r"^[a-z][a-z0-9._-]+$")
    capability: AdapterCapability
    backend: str = Field(min_length=1)
    path: str = Field(min_length=1)
    classification: Literal["public", "synthetic"]
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("path")
    @classmethod
    def path_must_be_a_relative_json_file(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".json":
            raise ValueError("fixture path must be a relative JSON file without traversal")
        return value


class FixtureManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_version: Literal[1] = Field(alias="schemaVersion")
    fixture_set_id: str = Field(alias="fixtureSetId", pattern=r"^[a-z0-9][a-z0-9._-]+$")
    revision: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]+$")
    records: tuple[FixtureRecord, ...]

    @model_validator(mode="after")
    def require_one_record_per_capability(self) -> Self:
        ids = [record.fixture_id for record in self.records]
        capabilities = [record.capability for record in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("fixture ids must be unique")
        if len(capabilities) != len(set(capabilities)):
            raise ValueError("fixture capabilities must be unique")
        if set(capabilities) != set(AdapterCapability):
            raise ValueError("fixture manifest must cover every adapter capability")
        for record in self.records:
            if record.backend != DEMO_BACKENDS[record.capability]:
                raise ValueError(
                    f"{record.capability.value} must use {DEMO_BACKENDS[record.capability]}"
                )
        return self


@dataclass(frozen=True, slots=True)
class FixtureCatalog:
    root: Path
    manifest: FixtureManifest
    _payloads: Mapping[AdapterCapability, Mapping[str, Any]] = field(repr=False)

    @classmethod
    def load(cls, root: Path | None = None) -> FixtureCatalog:
        try:
            fixture_root = (root or DEFAULT_FIXTURE_ROOT).resolve(strict=True)
            manifest_payload = cls._read_json(fixture_root, Path("manifest.json"))
            manifest = FixtureManifest.model_validate(manifest_payload)
            payloads: dict[AdapterCapability, Mapping[str, Any]] = {}
            for record in manifest.records:
                relative_path = Path(*PurePosixPath(record.path).parts)
                raw = cls._read_bytes(fixture_root, relative_path)
                digest = hashlib.sha256(raw).hexdigest()
                if not hmac.compare_digest(digest, record.sha256):
                    raise FixtureCatalogError(f"fixture digest mismatch: {record.fixture_id}")
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise FixtureCatalogError(
                        f"fixture payload must be an object: {record.fixture_id}"
                    )
                payloads[record.capability] = MappingProxyType(cast(dict[str, Any], parsed))
        except FixtureCatalogError:
            raise
        except (OSError, json.JSONDecodeError, ValidationError, ValueError) as error:
            raise FixtureCatalogError("fixture catalog validation failed") from error

        return cls(
            root=fixture_root,
            manifest=manifest,
            _payloads=MappingProxyType(payloads),
        )

    @staticmethod
    def _resolve_file(root: Path, relative_path: Path) -> Path:
        candidate = root / relative_path
        if candidate.is_symlink():
            raise FixtureCatalogError(f"fixture files cannot be symlinks: {relative_path}")
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(root)
        except (OSError, ValueError) as error:
            raise FixtureCatalogError(
                f"fixture path escapes catalog root: {relative_path}"
            ) from error
        if not resolved.is_file():
            raise FixtureCatalogError(f"fixture path is not a file: {relative_path}")
        return resolved

    @classmethod
    def _read_bytes(cls, root: Path, relative_path: Path) -> bytes:
        return cls._resolve_file(root, relative_path).read_bytes()

    @classmethod
    def _read_json(cls, root: Path, relative_path: Path) -> dict[str, Any]:
        parsed = json.loads(cls._read_bytes(root, relative_path))
        if not isinstance(parsed, dict):
            raise FixtureCatalogError(f"fixture JSON must be an object: {relative_path}")
        return cast(dict[str, Any], parsed)

    def payload(self, capability: AdapterCapability) -> Mapping[str, Any]:
        return self._payloads[capability]
