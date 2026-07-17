"""Privacy-bounded, cost-capped model routing gateway."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final, Literal, Protocol, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mandate_worker.fixtures import AdapterCapability
from mandate_worker.runtime import RuntimeAdapterPlan

OutputT = TypeVar("OutputT", bound=BaseModel)

FORBIDDEN_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "user_id",
        "user_name",
        "email",
        "phone",
        "firm",
        "firm_name",
        "billing",
        "payment",
        "letterhead",
        "logo",
        "confidential",
        "matter_narrative",
        "uploaded_document",
        "oauth_token",
        "password",
        "secret",
    }
)


class ModelGatewayError(RuntimeError):
    """Stable model-gateway failure without prompt or provider response detail."""


class ModelGatewayConfigurationError(ModelGatewayError):
    """Model routing is unconfigured or unsafe."""


class ModelPayloadRejected(ModelGatewayError):
    """Payload contains a field outside the task allowlist."""


class ModelCostCapExceeded(ModelGatewayError):
    """A call or job would exceed its configured model budget."""


class ModelOutputInvalid(ModelGatewayError):
    """Provider output remained invalid after one bounded repair attempt."""


class NoApprovedCapacity(ModelGatewayError):
    """No ZDR-capable allowlisted provider is available."""


class ModelTaskRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    task: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    model: str = Field(min_length=1, max_length=200)
    prompt_bundle_version: str = Field(min_length=1, max_length=100)
    allowed_payload_fields: frozenset[str] = Field(min_length=1, max_length=64)
    provider_allowlist: tuple[str, ...] = Field(min_length=1, max_length=8)
    max_input_tokens: int = Field(gt=0, le=200_000)
    max_output_tokens: int = Field(gt=0, le=32_000)
    max_cost_usd: Decimal = Field(gt=0, le=Decimal("25"))


class ModelBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    call_max_cost_usd: Decimal = Field(gt=0, le=Decimal("25"))
    job_remaining_cost_usd: Decimal = Field(gt=0, le=Decimal("100"))


class ModelProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str
    task: str
    prompt_bundle_version: str
    payload: Mapping[str, Any]
    response_schema: Mapping[str, Any]
    max_input_tokens: int
    max_output_tokens: int
    zdr: Literal[True] = True
    provider_allowlist: tuple[str, ...]
    repair: bool = False


class ModelProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    model: str
    output: Mapping[str, Any]
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)
    latency_ms: int = Field(ge=0)
    zdr_enforced: Literal[True] = True


class AgentRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_request_id: UUID
    job_id: UUID
    task: str
    model: str
    provider: str
    prompt_bundle_version: str
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal
    latency_ms: int
    zdr_enforced: Literal[True]
    repair_attempted: bool
    succeeded: bool
    error_code: str | None = None


class AgentRunSink(Protocol):
    async def record(self, run: AgentRunRecord) -> None: ...


class ModelRouter(Protocol):
    async def complete(self, request: ModelProviderRequest) -> ModelProviderResponse: ...


class FixtureModelRouter:
    def __init__(self, responses: Mapping[str, Mapping[str, Any]]) -> None:
        self._responses = dict(responses)

    async def complete(self, request: ModelProviderRequest) -> ModelProviderResponse:
        output = self._responses.get(request.task)
        if output is None:
            raise NoApprovedCapacity("fixture_model_task_missing")
        return ModelProviderResponse(
            provider="fixture",
            model=request.model,
            output=output,
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal("0"),
            latency_ms=0,
            zdr_enforced=True,
        )


class OpenRouterTransport(Protocol):
    async def __call__(self, request: ModelProviderRequest) -> ModelProviderResponse: ...


@dataclass(frozen=True, slots=True)
class OpenRouterModelRouter:
    transport: OpenRouterTransport

    async def complete(self, request: ModelProviderRequest) -> ModelProviderResponse:
        if not request.zdr or not request.provider_allowlist:
            raise ModelGatewayConfigurationError("zdr_or_provider_allowlist_missing")
        response = await self.transport(request)
        if not response.zdr_enforced or response.provider not in request.provider_allowlist:
            raise NoApprovedCapacity("provider_not_approved")
        return response


class MemoryAgentRunSink:
    def __init__(self) -> None:
        self.records: list[AgentRunRecord] = []

    async def record(self, run: AgentRunRecord) -> None:
        self.records.append(run)


class ModelGateway:
    def __init__(
        self,
        *,
        router: ModelRouter,
        routes: Mapping[str, ModelTaskRoute],
        run_sink: AgentRunSink,
    ) -> None:
        self._router = router
        self._routes = dict(routes)
        self._run_sink = run_sink

    async def complete(
        self,
        *,
        report_request_id: UUID,
        job_id: UUID,
        task: str,
        payload: Mapping[str, Any],
        output_type: type[OutputT],
        budget: ModelBudget,
    ) -> OutputT:
        route = self._routes.get(task)
        if route is None:
            raise ModelGatewayConfigurationError("model_task_not_routed")
        self._validate_payload(route, payload)
        effective_cap = min(
            route.max_cost_usd,
            budget.call_max_cost_usd,
            budget.job_remaining_cost_usd,
        )
        if effective_cap <= 0:
            raise ModelCostCapExceeded("model_budget_exhausted")

        response: ModelProviderResponse | None = None
        repair_attempted = False
        try:
            for attempt in range(2):
                repair_attempted = attempt == 1
                response = await self._router.complete(
                    ModelProviderRequest(
                        model=route.model,
                        task=route.task,
                        prompt_bundle_version=route.prompt_bundle_version,
                        payload=dict(payload),
                        response_schema=output_type.model_json_schema(),
                        max_input_tokens=route.max_input_tokens,
                        max_output_tokens=route.max_output_tokens,
                        provider_allowlist=route.provider_allowlist,
                        repair=repair_attempted,
                    )
                )
                self._enforce_response_budget(route, response, effective_cap)
                try:
                    parsed = output_type.model_validate(response.output)
                except ValidationError:
                    if not repair_attempted:
                        continue
                    raise ModelOutputInvalid("model_output_schema_invalid") from None
                await self._record(
                    report_request_id=report_request_id,
                    job_id=job_id,
                    route=route,
                    response=response,
                    repair_attempted=repair_attempted,
                    succeeded=True,
                )
                return parsed
            raise ModelOutputInvalid("model_output_schema_invalid")
        except ModelGatewayError as error:
            if response is not None:
                await self._record(
                    report_request_id=report_request_id,
                    job_id=job_id,
                    route=route,
                    response=response,
                    repair_attempted=repair_attempted,
                    succeeded=False,
                    error_code=str(error),
                )
            raise

    @staticmethod
    def _validate_payload(route: ModelTaskRoute, payload: Mapping[str, Any]) -> None:
        keys = set(payload)
        if keys - set(route.allowed_payload_fields):
            raise ModelPayloadRejected("model_payload_not_allowlisted")

        def walk(value: object) -> None:
            if isinstance(value, Mapping):
                for key, child in value.items():
                    if str(key).casefold() in FORBIDDEN_PAYLOAD_KEYS:
                        raise ModelPayloadRejected("nested_model_payload_forbidden")
                    walk(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    walk(child)

        walk(payload)

    @staticmethod
    def _enforce_response_budget(
        route: ModelTaskRoute,
        response: ModelProviderResponse,
        effective_cap: Decimal,
    ) -> None:
        if response.cost_usd > effective_cap:
            raise ModelCostCapExceeded("model_call_cost_cap_exceeded")
        if response.input_tokens > route.max_input_tokens:
            raise ModelCostCapExceeded("model_input_token_cap_exceeded")
        if response.output_tokens > route.max_output_tokens:
            raise ModelCostCapExceeded("model_output_token_cap_exceeded")

    async def _record(
        self,
        *,
        report_request_id: UUID,
        job_id: UUID,
        route: ModelTaskRoute,
        response: ModelProviderResponse,
        repair_attempted: bool,
        succeeded: bool,
        error_code: str | None = None,
    ) -> None:
        await self._run_sink.record(
            AgentRunRecord(
                report_request_id=report_request_id,
                job_id=job_id,
                task=route.task,
                model=response.model,
                provider=response.provider,
                prompt_bundle_version=route.prompt_bundle_version,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cost_usd=response.cost_usd,
                latency_ms=response.latency_ms,
                zdr_enforced=response.zdr_enforced,
                repair_attempted=repair_attempted,
                succeeded=succeeded,
                error_code=error_code,
            )
        )


class _ModelFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    fixture_version: Literal[1] = Field(alias="fixtureVersion")
    routes: tuple[ModelTaskRoute, ...]
    responses: Mapping[str, Mapping[str, Any]]


def build_model_gateway(
    plan: RuntimeAdapterPlan,
    *,
    run_sink: AgentRunSink,
    openrouter_transport: OpenRouterTransport | None = None,
    live_routes: Mapping[str, ModelTaskRoute] | None = None,
) -> ModelGateway:
    binding = plan.bindings[AdapterCapability.MODEL]
    if binding == "fixture":
        if not plan.demo_mode or plan.catalog is None:
            raise ModelGatewayConfigurationError("model_fixture_requires_demo_mode")
        fixture = _ModelFixture.model_validate(plan.catalog.payload(AdapterCapability.MODEL))
        return ModelGateway(
            router=FixtureModelRouter(fixture.responses),
            routes={route.task: route for route in fixture.routes},
            run_sink=run_sink,
        )
    if binding == "openrouter":
        if openrouter_transport is None or not live_routes:
            raise ModelGatewayConfigurationError("live_model_routes_unconfigured")
        return ModelGateway(
            router=OpenRouterModelRouter(openrouter_transport),
            routes=live_routes,
            run_sink=run_sink,
        )
    if binding == "unconfigured":
        raise ModelGatewayConfigurationError("model_provider_unconfigured")
    raise ModelGatewayConfigurationError("model_provider_not_allowlisted")
