from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from mandate_worker.main import TRACE_HEADER, create_app
from mandate_worker.observability import (
    REDACTED,
    REDACTED_BINARY,
    SYSTEM_TRACE_ID,
    configure_logging,
    ensure_trace_id,
    get_logger,
)


def test_NFR_04_health_propagates_a_valid_trace_id() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health", headers={TRACE_HEADER: "trace-health-0001"})

    assert response.status_code == 200
    assert response.headers[TRACE_HEADER] == "trace-health-0001"
    assert response.json() == {
        "status": "ok",
        "service": "mandate-worker",
        "version": "0.0.0",
    }


def test_NFR_04_health_replaces_an_untrusted_trace_header() -> None:
    with TestClient(create_app()) as client:
        response = client.get("/health", headers={TRACE_HEADER: "not valid with spaces"})

    trace_id = response.headers[TRACE_HEADER]
    assert len(trace_id) == 32
    assert trace_id.isalnum()


def test_SEC_05_renderer_health_surface_is_distinct() -> None:
    with TestClient(create_app(service_name="mandate-renderer")) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "mandate-renderer",
        "version": "0.0.0",
    }


def test_NFR_04_log_processor_always_supplies_trace_id() -> None:
    event = ensure_trace_id(None, "info", {"event": "worker_ready"})

    assert event["trace_id"] == SYSTEM_TRACE_ID


def test_SEC_09_logger_boundary_redacts_sensitive_and_nested_fields(
    capsys: pytest.CaptureFixture[str],
) -> None:
    configure_logging()
    get_logger().info(
        "provider_call",
        trace_id="trace-sec09-0001",
        provider="fixture",
        prompt_version="entity-v1",
        model_prompt_version="entity-v1",
        token_count=42,
        api_key="must-not-appear",
        prompt="must-not-appear",
        response={
            "authorization": "must-not-appear",
            "provider": "fixture",
        },
        attachment=b"must-not-appear",
    )

    output = capsys.readouterr().out
    event = json.loads(output.splitlines()[-1])

    assert "must-not-appear" not in output
    assert event["api_key"] == REDACTED
    assert event["prompt"] == REDACTED
    assert event["response"]["authorization"] == REDACTED
    assert event["attachment"] == REDACTED_BINARY
    assert event["provider"] == "fixture"
    assert event["response"]["provider"] == "fixture"
    assert event["prompt_version"] == "entity-v1"
    assert event["model_prompt_version"] == "entity-v1"
    assert event["token_count"] == 42
