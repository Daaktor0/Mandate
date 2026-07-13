from __future__ import annotations

from fastapi.testclient import TestClient
from mandate_worker.main import TRACE_HEADER, create_app
from mandate_worker.observability import SYSTEM_TRACE_ID, ensure_trace_id


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


def test_NFR_04_log_processor_always_supplies_trace_id() -> None:
    event = ensure_trace_id(None, "info", {"event": "worker_ready"})

    assert event["trace_id"] == SYSTEM_TRACE_ID
