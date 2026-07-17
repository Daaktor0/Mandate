from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from mandate_worker.providers.model_gateway import (
    FixtureModelRouter,
    MemoryAgentRunSink,
    ModelBudget,
    ModelCostCapExceeded,
    ModelGateway,
    ModelGatewayConfigurationError,
    ModelOutputInvalid,
    ModelPayloadRejected,
    ModelProviderRequest,
    ModelProviderResponse,
    ModelTaskRoute,
    NoApprovedCapacity,
    OpenRouterModelRouter,
    build_model_gateway,
)
from mandate_worker.runtime import build_runtime_adapter_plan
from pydantic import BaseModel, ConfigDict

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPOSITORY_ROOT / "fixtures" / "demo"


class SmokeOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    decisions: list[str]
    rationale: str


class ScriptedRouter:
    def __init__(self, outputs: list[Mapping[str, Any]], *, cost: str = "0.01") -> None:
        self.outputs = outputs
        self.cost = Decimal(cost)
        self.requests: list[ModelProviderRequest] = []

    async def complete(self, request: ModelProviderRequest) -> ModelProviderResponse:
        self.requests.append(request)
        output = self.outputs[min(len(self.requests) - 1, len(self.outputs) - 1)]
        return ModelProviderResponse(
            provider="approved",
            model=request.model,
            output=output,
            input_tokens=10,
            output_tokens=10,
            cost_usd=self.cost,
            latency_ms=1,
            zdr_enforced=True,
        )


def route() -> ModelTaskRoute:
    return ModelTaskRoute(
        task="phase2_smoke",
        model="approved/model",
        prompt_bundle_version="phase2-v1",
        allowed_payload_fields=frozenset(
            {"report_request_id", "evidence_ids", "admitted_content"}
        ),
        provider_allowlist=("approved",),
        max_input_tokens=100,
        max_output_tokens=100,
        max_cost_usd=Decimal("1"),
    )


def budget() -> ModelBudget:
    return ModelBudget(
        call_max_cost_usd=Decimal("1"),
        job_remaining_cost_usd=Decimal("2"),
    )


@pytest.mark.asyncio
async def test_RUN_05_01_demo_gateway_is_deterministic_and_zero_spend() -> None:
    plan = build_runtime_adapter_plan({"DEMO_MODE": "1"}, fixture_root=FIXTURE_ROOT)
    sink = MemoryAgentRunSink()
    gateway = build_model_gateway(plan, run_sink=sink)
    kwargs = {
        "report_request_id": uuid4(),
        "job_id": uuid4(),
        "task": "phase2_smoke",
        "payload": {
            "report_request_id": "public-request-id",
            "evidence_ids": ["evidence-1"],
            "admitted_content": "synthetic public evidence",
        },
        "output_type": SmokeOutput,
        "budget": budget(),
    }

    first = await gateway.complete(**kwargs)
    second = await gateway.complete(**kwargs)

    assert first == second
    assert len(sink.records) == 2
    assert all(record.provider == "fixture" for record in sink.records)
    assert all(record.cost_usd == Decimal("0") for record in sink.records)
    assert all(record.zdr_enforced is True for record in sink.records)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"report_request_id": "id", "user_id": "forbidden"},
        {
            "report_request_id": "id",
            "admitted_content": {"firm_name": "forbidden"},
        },
        {"report_request_id": "id", "confidential": "forbidden"},
        {"report_request_id": "id", "unknown": "forbidden"},
    ],
)
async def test_RUN_06_02_payload_allowlist_rejects_forbidden_injection(
    payload: Mapping[str, Any],
) -> None:
    gateway = ModelGateway(
        router=FixtureModelRouter({"phase2_smoke": {}}),
        routes={"phase2_smoke": route()},
        run_sink=MemoryAgentRunSink(),
    )

    with pytest.raises(ModelPayloadRejected):
        await gateway.complete(
            report_request_id=uuid4(),
            job_id=uuid4(),
            task="phase2_smoke",
            payload=payload,
            output_type=SmokeOutput,
            budget=budget(),
        )


@pytest.mark.asyncio
async def test_RUN_05_03_schema_validation_allows_one_repair_retry() -> None:
    router = ScriptedRouter(
        [
            {"status": "invalid"},
            {"status": "ok", "decisions": [], "rationale": "repaired"},
        ]
    )
    sink = MemoryAgentRunSink()
    gateway = ModelGateway(
        router=router,
        routes={"phase2_smoke": route()},
        run_sink=sink,
    )

    result = await gateway.complete(
        report_request_id=uuid4(),
        job_id=uuid4(),
        task="phase2_smoke",
        payload={"report_request_id": "id"},
        output_type=SmokeOutput,
        budget=budget(),
    )

    assert result.rationale == "repaired"
    assert [request.repair for request in router.requests] == [False, True]
    assert sink.records[0].repair_attempted is True
    assert sink.records[0].succeeded is True


@pytest.mark.asyncio
async def test_RUN_05_04_schema_validation_stops_after_one_repair_retry() -> None:
    router = ScriptedRouter([{"status": "invalid"}])
    sink = MemoryAgentRunSink()
    gateway = ModelGateway(
        router=router,
        routes={"phase2_smoke": route()},
        run_sink=sink,
    )

    with pytest.raises(ModelOutputInvalid):
        await gateway.complete(
            report_request_id=uuid4(),
            job_id=uuid4(),
            task="phase2_smoke",
            payload={"report_request_id": "id"},
            output_type=SmokeOutput,
            budget=budget(),
        )

    assert len(router.requests) == 2
    assert sink.records[-1].succeeded is False


@pytest.mark.asyncio
async def test_RUN_07_05_cost_cap_stops_over_budget_response() -> None:
    router = ScriptedRouter(
        [{"status": "ok", "decisions": [], "rationale": "too expensive"}],
        cost="1.01",
    )
    sink = MemoryAgentRunSink()
    gateway = ModelGateway(
        router=router,
        routes={"phase2_smoke": route()},
        run_sink=sink,
    )

    with pytest.raises(ModelCostCapExceeded):
        await gateway.complete(
            report_request_id=uuid4(),
            job_id=uuid4(),
            task="phase2_smoke",
            payload={"report_request_id": "id"},
            output_type=SmokeOutput,
            budget=budget(),
        )

    assert sink.records[-1].error_code == "model_call_cost_cap_exceeded"


@pytest.mark.asyncio
async def test_SEC_11_06_openrouter_rejects_non_allowlisted_provider() -> None:
    async def transport(request: ModelProviderRequest) -> ModelProviderResponse:
        assert request.zdr is True
        assert request.provider_allowlist == ("approved",)
        return ModelProviderResponse(
            provider="not-approved",
            model=request.model,
            output={"status": "ok", "decisions": [], "rationale": "unsafe"},
            input_tokens=1,
            output_tokens=1,
            cost_usd=Decimal("0.01"),
            latency_ms=1,
            zdr_enforced=True,
        )

    with pytest.raises(NoApprovedCapacity):
        await OpenRouterModelRouter(transport).complete(
            ModelProviderRequest(
                model="approved/model",
                task="phase2_smoke",
                prompt_bundle_version="phase2-v1",
                payload={"report_request_id": "id"},
                response_schema=SmokeOutput.model_json_schema(),
                max_input_tokens=100,
                max_output_tokens=100,
                provider_allowlist=("approved",),
            )
        )


@pytest.mark.parametrize("binding", ["unconfigured", "fixture", "other"])
def test_NFR_03_07_live_model_selection_fails_closed(binding: str) -> None:
    plan = build_runtime_adapter_plan(
        {"DEMO_MODE": "0", "PROVIDER_MODEL": binding},
        fixture_root=Path("/does/not/exist"),
    )
    with pytest.raises(ModelGatewayConfigurationError):
        build_model_gateway(plan, run_sink=MemoryAgentRunSink())


def test_SEC_11_08_live_openrouter_requires_routes_and_transport() -> None:
    plan = build_runtime_adapter_plan(
        {"DEMO_MODE": "0", "PROVIDER_MODEL": "openrouter"},
        fixture_root=Path("/does/not/exist"),
    )
    with pytest.raises(ModelGatewayConfigurationError):
        build_model_gateway(plan, run_sink=MemoryAgentRunSink())
