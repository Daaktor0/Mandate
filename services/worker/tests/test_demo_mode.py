from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from mandate_worker.fixtures import (
    DEMO_BACKENDS,
    AdapterCapability,
    FixtureCatalog,
    FixtureCatalogError,
)
from mandate_worker.main import create_app
from mandate_worker.runtime import (
    SELECTOR_ENV,
    RuntimeConfigurationError,
    build_runtime_adapter_plan,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPOSITORY_ROOT / "fixtures" / "demo"


def nested_keys(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key).lower()
            yield from nested_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_keys(child)


def test_NFR_03_ADR_014_catalog_covers_every_adapter_and_is_synthetic() -> None:
    catalog = FixtureCatalog.load(FIXTURE_ROOT)

    assert catalog.manifest.fixture_set_id == "phase-0-smoke-v1"
    assert {record.capability for record in catalog.manifest.records} == set(AdapterCapability)
    assert all(record.classification == "synthetic" for record in catalog.manifest.records)
    for capability in AdapterCapability:
        assert catalog.payload(capability)["fixtureVersion"] == 1


def test_INTAKE_04_demo_fixtures_exclude_identity_credentials_and_confidential_inputs() -> None:
    catalog = FixtureCatalog.load(FIXTURE_ROOT)
    forbidden_keys = {
        "api_key",
        "billing",
        "confidential",
        "email_address",
        "letterhead",
        "oauth_token",
        "password",
        "payment",
        "phone",
        "secret",
        "upload",
        "user_id",
    }

    fixture_keys = {
        key for capability in AdapterCapability for key in nested_keys(catalog.payload(capability))
    }
    assert fixture_keys.isdisjoint(forbidden_keys)


def test_NFR_03_ADR_014_catalog_rejects_payload_drift(tmp_path: Path) -> None:
    catalog_root = tmp_path / "demo"
    shutil.copytree(FIXTURE_ROOT, catalog_root)
    (catalog_root / "search" / "smoke.json").write_text("{}\n")

    with pytest.raises(FixtureCatalogError, match="digest mismatch"):
        FixtureCatalog.load(catalog_root)


def test_NFR_03_ADR_014_catalog_rejects_path_traversal(tmp_path: Path) -> None:
    catalog_root = tmp_path / "demo"
    shutil.copytree(FIXTURE_ROOT, catalog_root)
    manifest_path = catalog_root / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    records = manifest["records"]
    assert isinstance(records, list)
    first_record = records[0]
    assert isinstance(first_record, dict)
    first_record["path"] = "../outside.json"
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(FixtureCatalogError, match="validation failed"):
        FixtureCatalog.load(catalog_root)


def test_NFR_03_ADR_014_demo_mode_forces_zero_spend_bindings() -> None:
    live_selectors = {
        "DEMO_MODE": "1",
        "PROVIDER_SEARCH": "brave",
        "PROVIDER_PAGE_FETCHER": "safe_fetcher",
        "PROVIDER_COMPANY_DATA": "attestr",
        "PROVIDER_CORPORATE_FILINGS": "manual_mca_vpd",
        "PROVIDER_MALWARE_SCANNER": "clamd_unix",
        "PROVIDER_FILE_PARSER": "sandboxed_service",
        "PROVIDER_REGULATORY": "public_web",
        "PROVIDER_LITIGATION": "public_web",
        "PROVIDER_MODEL": "openrouter",
        "QUEUE_BACKEND": "pgmq",
        "STORAGE_BACKEND": "supabase",
        "EMAIL_PROVIDER": "resend",
        "SEARCH_API_KEY": "must-not-appear",
        "OPENROUTER_API_KEY": "must-not-appear",
    }

    plan = build_runtime_adapter_plan(live_selectors, fixture_root=FIXTURE_ROOT)

    assert plan.zero_spend is True
    assert plan.bindings == DEMO_BACKENDS
    assert plan.fixture_revision == "2026-07-17.3"
    assert plan.overridden_selectors == tuple(sorted(SELECTOR_ENV.values()))
    assert "must-not-appear" not in repr(plan)


def test_NFR_03_ADR_014_demo_mode_flag_is_strict() -> None:
    with pytest.raises(RuntimeConfigurationError, match="exactly '0' or '1'"):
        build_runtime_adapter_plan({"DEMO_MODE": "true"}, fixture_root=FIXTURE_ROOT)


def test_ENTITY_05_worker_rejects_unverified_attestr_live_binding() -> None:
    with pytest.raises(RuntimeConfigurationError, match="attestr is disabled"):
        create_app(
            environ={"DEMO_MODE": "0", "PROVIDER_COMPANY_DATA": "attestr"},
            fixture_root=FIXTURE_ROOT,
        )


def test_NFR_03_live_mode_does_not_load_or_silently_select_fixtures() -> None:
    plan = build_runtime_adapter_plan(
        {"DEMO_MODE": "0", "PROVIDER_SEARCH": "brave"},
        fixture_root=Path("/does/not/exist"),
    )

    assert plan.demo_mode is False
    assert plan.catalog is None
    assert plan.bindings[AdapterCapability.SEARCH] == "brave"
    assert plan.bindings[AdapterCapability.CORPORATE_FILINGS] == "unconfigured"
    assert plan.bindings[AdapterCapability.MODEL] == "unconfigured"


def test_NFR_03_worker_bootstraps_demo_catalog_but_renderer_has_no_provider_plan() -> None:
    worker = create_app(environ={"DEMO_MODE": "1"}, fixture_root=FIXTURE_ROOT)
    renderer = create_app(
        service_name="mandate-renderer",
        environ={"DEMO_MODE": "1"},
        fixture_root=FIXTURE_ROOT,
    )

    assert worker.state.runtime_adapter_plan.zero_spend is True
    assert not hasattr(renderer.state, "runtime_adapter_plan")
