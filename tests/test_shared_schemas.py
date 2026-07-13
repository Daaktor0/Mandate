from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest
from jsonschema import Draft202012Validator
from mandate_schemas import EntityCandidate, Evidence, JobMessage
from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_DIRECTORY = REPOSITORY_ROOT / "packages" / "shared-schemas" / "schemas"


def test_RUN_05_canonical_json_schemas_are_valid_draft_2020_12() -> None:
    for schema_path in sorted(SCHEMA_DIRECTORY.glob("*.json")):
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        assert schema["additionalProperties"] is False
        assert schema["properties"]["schemaVersion"]["const"] == 1


def test_RUN_05_generated_contracts_are_in_sync() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/generate_schemas.py", "--check"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_ENTITY_02_entity_candidate_accepts_a_public_hostname() -> None:
    candidate = EntityCandidate.model_validate(
        {
            "schemaVersion": 1,
            "candidateId": str(uuid4()),
            "legalName": "Example Private Limited",
            "companyType": "private",
            "primaryDomain": "example.com",
            "confidenceScore": 80,
            "confidenceLabel": "strong_match",
            "evidenceSnippets": [
                {
                    "evidenceId": str(uuid4()),
                    "snippet": "Owned and operated by Example Private Limited.",
                    "sourceUrl": "https://example.com/privacy",
                    "companyControlled": True,
                }
            ],
            "conflicts": [],
        }
    )

    assert candidate.primary_domain == "example.com"


def test_RUN_05_job_message_rejects_account_and_billing_fields() -> None:
    payload = {
        "schemaVersion": 1,
        "jobId": str(uuid4()),
        "reportRequestId": str(uuid4()),
        "userId": str(uuid4()),
        "confirmedEntityId": str(uuid4()),
        "attempt": 1,
        "traceId": "trace-schema-003",
        "budgetProfile": "mvp-standard",
        "userEmail": "lawyer@example.com",
    }

    with pytest.raises(ValidationError):
        JobMessage.model_validate(payload)


def test_RUN_04_evidence_contract_preserves_provenance_metadata() -> None:
    evidence = Evidence.model_validate(
        {
            "schemaVersion": 1,
            "evidenceId": str(uuid4()),
            "jobId": str(uuid4()),
            "url": "https://example.com/privacy",
            "canonicalUrl": "https://example.com/privacy",
            "title": "Privacy policy",
            "publisher": "Example",
            "sourceTier": 2,
            "accessedAt": "2026-07-13T12:00:00+05:30",
            "excerpt": "Owned and operated by Example Private Limited.",
            "contentHash": "a" * 64,
            "entityIdentifiers": {
                "legalNames": ["Example Private Limited"],
                "cins": [],
                "addresses": [],
            },
            "companyControlled": True,
            "extractionMethod": "fixture",
            "promptInjectionSuspected": False,
            "retentionClass": "with_report",
        }
    )

    assert evidence.source_tier == 2
    assert evidence.company_controlled is True
    assert evidence.entity_identifiers.legal_names == ["Example Private Limited"]
