from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest
from mandate_worker.providers.corporate_filings import (
    CorporateFilingAcquisitionMethod,
    CorporateFilingAcquisitionResult,
    CorporateFilingAcquisitionStatus,
    CorporateFilingActionCode,
    CorporateFilingRequest,
    CorporateFilingType,
    FixtureCorporateFilingProvider,
    ManualMcaVpdProvider,
    register_untrusted_corporate_filing,
)
from pydantic import ValidationError

PRIVATE_CIN = "U62099MH2024PTC123456"


def filing_reference(*, filing_type: CorporateFilingType, financial_year: str):
    body = f"synthetic-{filing_type.value}-{financial_year}".encode()
    return register_untrusted_corporate_filing(
        document_id=f"fixture:{filing_type.value}:{financial_year}",
        cin=PRIVATE_CIN,
        filing_type=filing_type,
        financial_year=financial_year,
        acquisition_method=CorporateFilingAcquisitionMethod.FIXTURE,
        source_provider="fixture",
        source_locator=f"fixture/{filing_type.value}/{financial_year}",
        media_type="application/pdf",
        body=body,
        acquired_at=datetime(2026, 7, 15, tzinfo=timezone.utc),
    )


def test_INTAKE_04_filing_request_is_public_identifier_only() -> None:
    with pytest.raises(ValidationError):
        CorporateFilingRequest.model_validate(
            {
                "cin": PRIVATE_CIN,
                "filing_types": ["aoc_4"],
                "user_id": "forbidden",
                "confidential_matter": "forbidden",
            }
        )


@pytest.mark.asyncio
async def test_RUN_06_manual_vpd_requires_human_action_without_credentials_or_calls() -> None:
    request = CorporateFilingRequest(
        cin=PRIVATE_CIN.lower(),
        filing_types=(CorporateFilingType.AOC_4, CorporateFilingType.MGT_7),
        financial_years=("2024-25",),
    )

    result = await ManualMcaVpdProvider().acquire(request)

    assert result.request.cin == PRIVATE_CIN
    assert result.status is CorporateFilingAcquisitionStatus.HUMAN_ACTION_REQUIRED
    assert result.action_code is CorporateFilingActionCode.MCA_VPD_LOGIN_PAYMENT_REQUIRED
    assert result.provider_calls == 0
    assert result.documents == ()
    assert "password" not in result.model_dump_json().casefold()
    assert "captcha" not in result.model_dump_json().casefold()


def test_SEC_03_acquired_document_is_hashed_and_quarantined_before_parsing() -> None:
    body = b"synthetic public filing"

    document = register_untrusted_corporate_filing(
        document_id="mca-vpd:transaction-123:document-1",
        cin=PRIVATE_CIN,
        filing_type=CorporateFilingType.MGT_7,
        acquisition_method=CorporateFilingAcquisitionMethod.MANUAL_MCA_VPD,
        source_provider="mca_vpd_manual",
        source_locator="transaction-123/document-1",
        media_type="application/pdf",
        body=body,
    )

    assert document.sha256 == hashlib.sha256(body).hexdigest()
    assert document.size_bytes == len(body)
    assert document.quarantine_status == "pending_malware_scan"
    assert document.parse_allowed is False


def test_SEC_09_source_locator_rejects_embedded_credentials() -> None:
    with pytest.raises(ValidationError, match="must not contain credentials"):
        register_untrusted_corporate_filing(
            document_id="vendor:document-1",
            cin=PRIVATE_CIN,
            filing_type=CorporateFilingType.AOC_4,
            acquisition_method=CorporateFilingAcquisitionMethod.LICENSED_VENDOR,
            source_provider="licensed_vendor",
            source_locator="order-1?api_key=must-not-be-stored",
            media_type="application/pdf",
            body=b"synthetic",
        )


@pytest.mark.asyncio
async def test_RUN_06_fixture_provider_filters_type_and_financial_year() -> None:
    aoc = filing_reference(filing_type=CorporateFilingType.AOC_4, financial_year="2024-25")
    mgt = filing_reference(filing_type=CorporateFilingType.MGT_7, financial_year="2023-24")
    provider = FixtureCorporateFilingProvider({PRIVATE_CIN: (aoc, mgt)})
    request = CorporateFilingRequest(
        cin=PRIVATE_CIN,
        filing_types=(CorporateFilingType.AOC_4, CorporateFilingType.MGT_7),
        financial_years=("2024-25",),
    )

    result = await provider.acquire(request)

    assert result.status is CorporateFilingAcquisitionStatus.READY
    assert result.fixture is True
    assert result.provider_calls == 0
    assert result.documents == (aoc,)


def test_RUN_06_ready_result_cannot_claim_success_without_documents() -> None:
    request = CorporateFilingRequest(
        cin=PRIVATE_CIN,
        filing_types=(CorporateFilingType.AOC_4,),
    )

    with pytest.raises(ValidationError, match="requires documents"):
        CorporateFilingAcquisitionResult(
            request=request,
            provider="fixture",
            fixture=True,
            provider_calls=0,
            status=CorporateFilingAcquisitionStatus.READY,
        )
