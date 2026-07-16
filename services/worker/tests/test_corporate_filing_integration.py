from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from mandate_worker.providers.corporate_filing_integration import (
    ConfirmedCorporateFilingCommand,
    CorporateFilingConfigurationError,
    acquire_confirmed_corporate_filings,
    build_corporate_filing_provider,
)
from mandate_worker.providers.corporate_filings import (
    CorporateFilingAcquisitionStatus,
    CorporateFilingRequest,
    CorporateFilingType,
    FixtureCorporateFilingProvider,
    ManualMcaVpdProvider,
)
from mandate_worker.runtime import build_runtime_adapter_plan
from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPOSITORY_ROOT / "fixtures" / "demo"
PRIVATE_CIN = "U62099MH2024PTC123456"


@pytest.mark.asyncio
async def test_RUN_06_demo_provider_returns_only_quarantined_fixture_documents() -> None:
    plan = build_runtime_adapter_plan({"DEMO_MODE": "1"}, fixture_root=FIXTURE_ROOT)
    provider = build_corporate_filing_provider(plan)

    assert isinstance(provider, FixtureCorporateFilingProvider)
    result = await provider.acquire(
        CorporateFilingRequest(
            cin=PRIVATE_CIN,
            filing_types=(CorporateFilingType.AOC_4, CorporateFilingType.MGT_7),
            financial_years=("2024-25",),
        )
    )

    assert result.status is CorporateFilingAcquisitionStatus.READY
    assert len(result.documents) == 2
    assert all(
        document.quarantine_status == "pending_malware_scan" for document in result.documents
    )
    assert all(document.parse_allowed is False for document in result.documents)


def test_INTAKE_04_confirmed_command_rejects_identity_and_unconfirmed_state() -> None:
    request = CorporateFilingRequest(
        cin=PRIVATE_CIN,
        filing_types=(CorporateFilingType.AOC_4,),
    )

    with pytest.raises(ValidationError):
        ConfirmedCorporateFilingCommand.model_validate(
            {
                "report_request_id": str(uuid4()),
                "confirmed_entity_id": str(uuid4()),
                "report_state": "awaiting_entity_confirmation",
                "request": request.model_dump(mode="json"),
                "user_id": "forbidden",
            }
        )


@pytest.mark.asyncio
async def test_ENTITY_03_live_manual_acquisition_requires_confirmed_command() -> None:
    plan = build_runtime_adapter_plan(
        {
            "DEMO_MODE": "0",
            "PROVIDER_CORPORATE_FILINGS": "manual_mca_vpd",
        },
        fixture_root=Path("/does/not/exist"),
    )
    provider = build_corporate_filing_provider(plan)
    command = ConfirmedCorporateFilingCommand(
        report_request_id=uuid4(),
        confirmed_entity_id=uuid4(),
        request=CorporateFilingRequest(
            cin=PRIVATE_CIN,
            filing_types=(CorporateFilingType.AOC_4,),
        ),
    )

    result = await acquire_confirmed_corporate_filings(provider, command)

    assert isinstance(provider, ManualMcaVpdProvider)
    assert result.report_request_id == command.report_request_id
    assert result.confirmed_entity_id == command.confirmed_entity_id
    assert result.acquisition.status is CorporateFilingAcquisitionStatus.HUMAN_ACTION_REQUIRED
    assert result.acquisition.provider_calls == 0


@pytest.mark.parametrize("binding", ["fixture", "probe42", "finanvo"])
def test_NFR_03_live_unverified_filing_bindings_fail_closed(binding: str) -> None:
    plan = build_runtime_adapter_plan(
        {"DEMO_MODE": "0", "PROVIDER_CORPORATE_FILINGS": binding},
        fixture_root=Path("/does/not/exist"),
    )

    with pytest.raises(CorporateFilingConfigurationError):
        build_corporate_filing_provider(plan)
