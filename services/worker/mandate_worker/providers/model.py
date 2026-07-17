"""Typed, bounded model gateway boundary.

The gateway accepts only task identifiers, public-research excerpts and generic role
context. It cannot carry user identity, firm, billing, letterhead or confidential matter
narrative fields.
"""

from __future__ import annotations

import json
import math
import os
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Final, Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

import httpx
import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from mandate_worker.fixtures import AdapterCapability, FixtureCatalog
from mandate_worker.observability import get_logger
from mandate_worker.prompting import PromptEvidence, build_prompt_bundle
from mandate_worker.runtime import RuntimeAdapterPlan

OPENROUTER_CHAT_COMPLETIONS_URL: Final = "https://openrouter.ai/api/v1/chat/completions"
MAX_MODEL_RESPONSE_BYTES: Final = 2_097_152
MAX_REPAIR_SUMMARY_CHARS: Final = 600
MAX_MESSAGES: Final = 8
_DECIMAL_THOUSAND: Final = Decimal(1000)
_ALLOWED_IDENTIFIER_KEYS: Final = frozenset({"job_id", "request_id", "entity_id", "trace_id"})


class ModelConfigurationError(RuntimeError):
    """Model-provider selection, routing or credentials are absent or unsafe."""


class ModelGatewayError(RuntimeError):
    """Stable gateway failure that never contains prompt, output or secret text."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class NoApprovedCapacity(ModelGatewayError):
    """No allowlisted ZDR capacity is available."""


class ModelSchemaError(ModelGatewayError):
    """The model response failed caller schema validation after repair."""


class ModelBudgetExceeded(ModelGatewayError):
    """A per-call or per-job model budget would be breached."""


class ModelTransportError(RuntimeError):
    """Sanitised transport failure."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class EvidenceExcerpt(BaseModel):
    """Admitted public-research text only."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,64}$")
    source_url: str | None = Field(max_length=2_048)
    tier: int = Field(ge=1, le=4)
    company_controlled: bool
    text: str = Field(min_length=1, max_length=20_000)

    @field_validator("source_url")
    @classmethod
    def source_url_must_be_https(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _normalise_https_url(value)


class ModelTaskPayload(BaseModel):
    """Strict model-call payload allowlist."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    prompt_bundle_version: str = Field(pattern=r"^[A-Za-z0-9.-]{1,64}$")
    identifiers: dict[str, str]
    excerpts: tuple[EvidenceExcerpt, ...] = Field(max_length=64)
    context_role: Literal["investor", "acquirer", "partner", "generic"] = "generic"

    @field_validator("identifiers")
    @classmethod
    def identifiers_must_be_allowlisted(cls, value: dict[str, str]) -> dict[str, str]:
        if not set(value).issubset(_ALLOWED_IDENTIFIER_KEYS):
            raise ValueError("model identifiers contain non-allowlisted keys")
        for identifier_value in value.values():
            if not isinstance(identifier_value, str):
                raise ValueError("model identifier values must be strings")
            if not _IDENTIFIER_VALUE_PATTERN.fullmatch(identifier_value):
                raise ValueError("model identifier value is invalid")
        return value


class ModelBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_output_tokens: int = Field(gt=0, le=16_000)
    max_call_cost_inr: Decimal = Field(gt=0)
    job_cost_remaining_inr: Decimal = Field(ge=0)


class ModelRoute(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    model: str = Field(pattern=r"^[a-z0-9][a-z0-9/:._-]{1,127}$")
    zdr: Literal["required"]
    providers_allow: tuple[str, ...] = Field(min_length=1)
    cost_inr_per_1k_input: Decimal = Field(ge=0)
    cost_inr_per_1k_output: Decimal = Field(ge=0)


class ModelTier(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    primary: ModelRoute
    fallback: ModelRoute | None = None


class TaskOverride(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tier: Literal["low", "mid", "frontier"]
    max_output_tokens: int | None = Field(default=None, gt=0, le=16_000)


class RoutingConfig(BaseModel):
    """Versioned task-to-model policy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}\.[0-9]+$")
    tiers: dict[Literal["low", "mid", "frontier"], ModelTier]
    task_overrides: dict[str, TaskOverride]

    @model_validator(mode="after")
    def require_all_tiers(self) -> RoutingConfig:
        if set(self.tiers) != {"low", "mid", "frontier"}:
            raise ValueError("model routing tiers must include low, mid and frontier")
        return self

    @classmethod
    def load(cls, path: Path) -> RoutingConfig:
        try:
            with path.open("rb") as handle:
                raw = yaml.safe_load(handle)
            return cls.model_validate(raw)
        except (OSError, TypeError, yaml.YAMLError, ValidationError, ValueError) as error:
            raise ModelConfigurationError("model_routing_config_invalid") from error

    def resolve(self, task: str) -> tuple[ModelRoute, TaskOverride]:
        try:
            override = self.task_overrides[task]
            tier = self.tiers[override.tier]
        except KeyError as error:
            raise ModelConfigurationError("model_task_unrouted") from error
        return tier.primary, override


class AgentRunRecord(BaseModel):
    """Audit-safe record emitted for each model gateway invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    job_id: str | None = Field(default=None, max_length=128)
    task: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    model_id: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=50)
    prompt_version: str = Field(pattern=r"^[A-Za-z0-9.-]{1,64}$")
    routing_version: str = Field(min_length=1, max_length=64)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    cost_inr: Decimal = Field(ge=0)
    latency_ms: int = Field(ge=0)
    zdr_enforced: bool
    result: Literal["ok", "schema_retry_ok", "error", "refused"]
    error_detail: str | None = Field(default=None, max_length=200)

    @field_validator("zdr_enforced")
    @classmethod
    def zdr_must_be_true(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("agent run records must prove ZDR enforcement")
        return value


class AgentRunSink(Protocol):
    def record(self, run: AgentRunRecord) -> None:
        """Persist or emit an audit-safe model run record."""


class LoggingAgentRunSink:
    """Structured-log sink until the `agent_runs` table lands."""

    def record(self, run: AgentRunRecord) -> None:
        get_logger().info(
            "model.agent_run",
            job_id=run.job_id,
            task=run.task,
            model_id=run.model_id,
            provider=run.provider,
            prompt_version=run.prompt_version,
            routing_version=run.routing_version,
            input_tokens=run.input_tokens,
            output_tokens=run.output_tokens,
            cost_inr=str(run.cost_inr),
            latency_ms=run.latency_ms,
            zdr_enforced=run.zdr_enforced,
            result=run.result,
            error_detail=run.error_detail,
        )


@dataclass(frozen=True, slots=True)
class ModelCompletion[TResponse: BaseModel]:
    parsed: TResponse
    run: AgentRunRecord
    fixture: bool


class ModelGateway(Protocol):
    async def complete[TResponse: BaseModel](
        self,
        payload: ModelTaskPayload,
        budget: ModelBudget,
        response_model: type[TResponse],
    ) -> ModelCompletion[TResponse]:
        """Return a caller-validated structured model response."""


class ModelHttpResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status_code: int = Field(ge=100, le=599)
    content_type: str | None = Field(default=None, max_length=200)
    body: bytes = Field(max_length=MAX_MODEL_RESPONSE_BYTES)


class ModelTransport(Protocol):
    async def post_json(self, payload: Mapping[str, object]) -> ModelHttpResponse:
        """POST an allowlisted payload to the selected model endpoint."""


@dataclass(frozen=True, slots=True)
class OpenRouterHttpTransport:
    """No-proxy, no-redirect transport restricted to OpenRouter chat completions."""

    api_key: str = field(repr=False)
    timeout_seconds: float = 30.0
    max_response_bytes: int = MAX_MODEL_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ModelConfigurationError("model_credentials_missing")
        if not 0 < self.timeout_seconds <= 60:
            raise ModelConfigurationError("model_timeout_invalid")
        if not 1 <= self.max_response_bytes <= MAX_MODEL_RESPONSE_BYTES:
            raise ModelConfigurationError("model_response_cap_invalid")

    async def post_json(self, payload: Mapping[str, object]) -> ModelHttpResponse:
        headers = {
            "Accept": "application/json",
            "Accept-Encoding": "identity",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Mandate-ModelGateway/1.0",
        }
        timeout = httpx.Timeout(self.timeout_seconds)
        try:
            async with httpx.AsyncClient(
                follow_redirects=False,
                trust_env=False,
                timeout=timeout,
            ) as client:
                async with client.stream(
                    "POST",
                    OPENROUTER_CHAT_COMPLETIONS_URL,
                    headers=headers,
                    json=dict(payload),
                ) as response:
                    body = bytearray()
                    async for chunk in response.aiter_raw():
                        body.extend(chunk)
                        if len(body) > self.max_response_bytes:
                            raise ModelTransportError(
                                "model_response_too_large",
                                retryable=False,
                            )
                    parsed = ModelHttpResponse(
                        status_code=response.status_code,
                        content_type=response.headers.get("content-type"),
                        body=bytes(body),
                    )
                    failure = _classify_http_failure(parsed)
                    if failure is not None:
                        raise failure
                    return parsed
        except ModelTransportError:
            raise
        except httpx.TransportError as error:
            raise ModelTransportError("model_transport_failed", retryable=True) from error


class _ModelFixtureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    task: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    prompt_bundle_version: str = Field(alias="promptBundleVersion")


class _ModelFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    fixture_version: Literal[1] = Field(alias="fixtureVersion")
    request: _ModelFixtureRequest
    response: dict[str, object]


@dataclass(frozen=True, slots=True)
class FixtureModelGateway:
    """Deterministic, zero-spend model implementation for demo mode."""

    fixture_task: str
    fixture_prompt_bundle_version: str
    fixture_response: Mapping[str, object]
    sink: AgentRunSink = field(default_factory=LoggingAgentRunSink)

    @classmethod
    def from_catalog(
        cls,
        catalog: FixtureCatalog,
        *,
        sink: AgentRunSink | None = None,
    ) -> FixtureModelGateway:
        try:
            fixture = _ModelFixture.model_validate(catalog.payload(AdapterCapability.MODEL))
        except (KeyError, ValidationError, ValueError) as error:
            raise ModelConfigurationError("model_fixture_invalid") from error
        return cls(
            fixture_task=fixture.request.task,
            fixture_prompt_bundle_version=fixture.request.prompt_bundle_version,
            fixture_response=fixture.response,
            sink=LoggingAgentRunSink() if sink is None else sink,
        )

    async def complete[TResponse: BaseModel](
        self,
        payload: ModelTaskPayload,
        budget: ModelBudget,
        response_model: type[TResponse],
    ) -> ModelCompletion[TResponse]:
        del budget
        started = time.monotonic()
        if payload.task != self.fixture_task:
            raise ModelConfigurationError("model_fixture_task_unknown")
        try:
            parsed = response_model.model_validate(self.fixture_response)
        except ValidationError as error:
            raise ModelSchemaError("model_fixture_schema_mismatch", retryable=False) from error

        run = AgentRunRecord(
            job_id=payload.identifiers.get("job_id"),
            task=payload.task,
            model_id="fixture",
            provider="fixture",
            prompt_version=self.fixture_prompt_bundle_version,
            routing_version="fixture",
            input_tokens=0,
            output_tokens=0,
            cost_inr=Decimal(0),
            latency_ms=_elapsed_ms(started),
            zdr_enforced=True,
            result="ok",
            error_detail=None,
        )
        self.sink.record(run)
        return ModelCompletion(parsed=parsed, run=run, fixture=True)


@dataclass(frozen=True, slots=True)
class OpenRouterModelGateway:
    """Structured-output gateway for one allowlisted OpenRouter route."""

    transport: ModelTransport
    routing: RoutingConfig
    sink: AgentRunSink = field(default_factory=LoggingAgentRunSink)

    async def complete[TResponse: BaseModel](
        self,
        payload: ModelTaskPayload,
        budget: ModelBudget,
        response_model: type[TResponse],
    ) -> ModelCompletion[TResponse]:
        started = time.monotonic()
        route, override = self.routing.resolve(payload.task)
        effective_max_output_tokens = _effective_max_output_tokens(budget, override)
        estimated_input_tokens = _estimate_payload_tokens(payload)
        worst_case_cost = _cost_for_tokens(
            estimated_input_tokens,
            effective_max_output_tokens,
            route,
        )
        if _budget_breached(worst_case_cost, budget):
            self._record(
                payload,
                route,
                started,
                input_tokens=0,
                output_tokens=0,
                cost_inr=Decimal(0),
                result="refused",
                error_detail="model_cost_cap_exceeded",
            )
            raise ModelBudgetExceeded("model_cost_cap_exceeded", retryable=False)

        messages = _base_messages(payload)
        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = Decimal(0)

        try:
            attempt = await self._attempt(
                route=route,
                messages=messages,
                effective_max_output_tokens=effective_max_output_tokens,
                response_model=response_model,
            )
        except ModelTransportError as error:
            self._record_transport_error(payload, route, started, error)
            raise _gateway_error_from_transport(error) from error

        total_input_tokens += attempt.input_tokens
        total_output_tokens += attempt.output_tokens
        total_cost += attempt.cost_inr
        if attempt.parsed is not None:
            if _actual_budget_breached(total_cost, budget):
                self._record_actual_budget_breach(
                    payload,
                    route,
                    started,
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    cost_inr=total_cost,
                )
            _raise_if_actual_budget_breached(total_cost, budget)
            run = self._record(
                payload,
                route,
                started,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cost_inr=total_cost,
                result="ok",
                error_detail=None,
            )
            return ModelCompletion(parsed=attempt.parsed, run=run, fixture=False)

        repair_messages: list[dict[str, object]] = [
            *messages,
            {
                "role": "user",
                "content": _repair_message(attempt.validation_summary),
            },
        ]
        retry_estimated_input_tokens = _estimate_message_tokens(repair_messages)
        retry_projected_cost = total_cost + _cost_for_tokens(
            retry_estimated_input_tokens,
            effective_max_output_tokens,
            route,
        )
        if _budget_breached(retry_projected_cost, budget):
            self._record(
                payload,
                route,
                started,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cost_inr=total_cost,
                result="error",
                error_detail="model_cost_cap_exceeded",
            )
            raise ModelBudgetExceeded("model_cost_cap_exceeded", retryable=False)

        try:
            retry_attempt = await self._attempt(
                route=route,
                messages=repair_messages,
                effective_max_output_tokens=effective_max_output_tokens,
                response_model=response_model,
            )
        except ModelTransportError as error:
            self._record_transport_error(payload, route, started, error)
            raise _gateway_error_from_transport(error) from error

        total_input_tokens += retry_attempt.input_tokens
        total_output_tokens += retry_attempt.output_tokens
        total_cost += retry_attempt.cost_inr
        if _actual_budget_breached(total_cost, budget):
            self._record_actual_budget_breach(
                payload,
                route,
                started,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cost_inr=total_cost,
            )
        _raise_if_actual_budget_breached(total_cost, budget)
        if retry_attempt.parsed is not None:
            run = self._record(
                payload,
                route,
                started,
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                cost_inr=total_cost,
                result="schema_retry_ok",
                error_detail=None,
            )
            return ModelCompletion(parsed=retry_attempt.parsed, run=run, fixture=False)

        self._record(
            payload,
            route,
            started,
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cost_inr=total_cost,
            result="error",
            error_detail="model_schema_invalid_after_repair",
        )
        raise ModelSchemaError("model_schema_invalid_after_repair", retryable=False)

    async def _attempt[TResponse: BaseModel](
        self,
        *,
        route: ModelRoute,
        messages: list[dict[str, object]],
        effective_max_output_tokens: int,
        response_model: type[TResponse],
    ) -> _ModelAttempt[TResponse]:
        payload = _openrouter_payload(route, messages, effective_max_output_tokens)
        response = await self.transport.post_json(payload)
        failure = _classify_http_failure(response)
        if failure is not None:
            raise failure
        return _parse_model_attempt(response.body, route, response_model)

    def _record(
        self,
        payload: ModelTaskPayload,
        route: ModelRoute,
        started: float,
        *,
        input_tokens: int,
        output_tokens: int,
        cost_inr: Decimal,
        result: Literal["ok", "schema_retry_ok", "error", "refused"],
        error_detail: str | None,
    ) -> AgentRunRecord:
        run = AgentRunRecord(
            job_id=payload.identifiers.get("job_id"),
            task=payload.task,
            model_id=route.model,
            provider="openrouter",
            prompt_version=payload.prompt_bundle_version,
            routing_version=self.routing.version,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_inr=cost_inr,
            latency_ms=_elapsed_ms(started),
            zdr_enforced=True,
            result=result,
            error_detail=error_detail,
        )
        self.sink.record(run)
        return run

    def _record_actual_budget_breach(
        self,
        payload: ModelTaskPayload,
        route: ModelRoute,
        started: float,
        *,
        input_tokens: int,
        output_tokens: int,
        cost_inr: Decimal,
    ) -> None:
        self._record(
            payload,
            route,
            started,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_inr=cost_inr,
            result="error",
            error_detail="model_cost_cap_exceeded",
        )

    def _record_transport_error(
        self,
        payload: ModelTaskPayload,
        route: ModelRoute,
        started: float,
        error: ModelTransportError,
    ) -> None:
        self._record(
            payload,
            route,
            started,
            input_tokens=0,
            output_tokens=0,
            cost_inr=Decimal(0),
            result="error",
            error_detail="no_approved_capacity"
            if error.code == "no_approved_capacity"
            else error.code,
        )


def build_model_gateway(
    plan: RuntimeAdapterPlan,
    *,
    environ: Mapping[str, str] | None = None,
    transport: ModelTransport | None = None,
    sink: AgentRunSink | None = None,
) -> ModelGateway:
    """Build the selected gateway without credential-driven fallback."""

    binding = plan.bindings[AdapterCapability.MODEL]
    if binding == "fixture":
        if not plan.demo_mode or plan.catalog is None:
            raise ModelConfigurationError("model_fixture_requires_demo_mode")
        return FixtureModelGateway.from_catalog(plan.catalog, sink=sink)
    if binding == "openrouter":
        environment = os.environ if environ is None else environ
        config_path_raw = environment.get("MODEL_ROUTING_CONFIG", "").strip()
        if not config_path_raw:
            raise ModelConfigurationError("model_routing_config_missing")
        routing = RoutingConfig.load(Path(config_path_raw))
        if transport is None:
            api_key = environment.get("OPENROUTER_API_KEY", "").strip()
            if not api_key:
                raise ModelConfigurationError("model_credentials_missing")
            transport = OpenRouterHttpTransport(api_key)
        return OpenRouterModelGateway(
            transport=transport,
            routing=routing,
            sink=LoggingAgentRunSink() if sink is None else sink,
        )
    if binding == "unconfigured":
        raise ModelConfigurationError("model_provider_unconfigured")
    raise ModelConfigurationError("model_provider_not_allowlisted")


_IDENTIFIER_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class _OpenRouterUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)


class _OpenRouterMessage(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    content: str = Field(min_length=1, max_length=MAX_MODEL_RESPONSE_BYTES)


class _OpenRouterChoice(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    message: _OpenRouterMessage


class _OpenRouterResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)

    choices: tuple[_OpenRouterChoice, ...] = Field(min_length=1, max_length=8)
    usage: _OpenRouterUsage


@dataclass(frozen=True, slots=True)
class _ModelAttempt[TResponse: BaseModel]:
    parsed: TResponse | None
    input_tokens: int
    output_tokens: int
    cost_inr: Decimal
    validation_summary: str


def _base_messages(payload: ModelTaskPayload) -> list[dict[str, object]]:
    bundle = build_prompt_bundle(
        task=payload.task,
        version=payload.prompt_bundle_version,
        identifiers=payload.identifiers,
        context_role=payload.context_role,
        excerpts=tuple(
            PromptEvidence.model_validate(excerpt.model_dump(mode="python"))
            for excerpt in payload.excerpts
        ),
    )
    return bundle.messages()


def _openrouter_payload(
    route: ModelRoute,
    messages: list[dict[str, object]],
    max_tokens: int,
) -> Mapping[str, object]:
    return {
        "model": route.model,
        "messages": messages[:MAX_MESSAGES],
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "provider": {
            "data_collection": "deny",
            "zdr": True,
            "only": list(route.providers_allow),
            "allow_fallbacks": False,
        },
    }


def _parse_model_attempt[TResponse: BaseModel](
    body: bytes,
    route: ModelRoute,
    response_model: type[TResponse],
) -> _ModelAttempt[TResponse]:
    try:
        raw = json.loads(body)
        response = _OpenRouterResponse.model_validate(raw)
    except json.JSONDecodeError as error:
        return _ModelAttempt(
            parsed=None,
            input_tokens=0,
            output_tokens=0,
            cost_inr=Decimal(0),
            validation_summary=f"response_json_invalid:{error.pos}",
        )
    except ValidationError as error:
        raise ModelGatewayError("model_response_invalid", retryable=False) from error

    cost = _cost_for_tokens(
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
        route,
    )
    content = response.choices[0].message.content
    try:
        parsed = response_model.model_validate_json(content)
    except (ValidationError, ValueError) as error:
        return _ModelAttempt(
            parsed=None,
            input_tokens=response.usage.prompt_tokens,
            output_tokens=response.usage.completion_tokens,
            cost_inr=cost,
            validation_summary=_validation_summary(error),
        )
    return _ModelAttempt(
        parsed=parsed,
        input_tokens=response.usage.prompt_tokens,
        output_tokens=response.usage.completion_tokens,
        cost_inr=cost,
        validation_summary="",
    )


def _validation_summary(error: ValidationError | ValueError) -> str:
    if isinstance(error, ValidationError):
        parts: list[str] = []
        for item in error.errors(include_input=False)[:10]:
            location = ".".join(str(part) for part in item.get("loc", ())) or "root"
            error_type = str(item.get("type", "invalid"))
            parts.append(f"{location}:{error_type}")
        summary = ";".join(parts) or "schema_invalid"
        return summary[:MAX_REPAIR_SUMMARY_CHARS]
    return type(error).__name__[:MAX_REPAIR_SUMMARY_CHARS]


def _repair_message(summary: str) -> str:
    bounded = summary[:MAX_REPAIR_SUMMARY_CHARS]
    return f"Return valid JSON only. Schema validation summary: {bounded}"


def _classify_http_failure(response: ModelHttpResponse) -> ModelTransportError | None:
    if response.status_code == 404 or _body_has_no_approved_capacity(response.body):
        return ModelTransportError("no_approved_capacity", retryable=True)
    if response.status_code == 200:
        media_type = (response.content_type or "").partition(";")[0].strip().lower()
        if media_type != "application/json":
            return ModelTransportError("model_response_invalid", retryable=False)
        return None
    if response.status_code == 400:
        return ModelTransportError("model_invalid_request", retryable=False)
    if response.status_code in {401, 403}:
        return ModelTransportError("model_unauthorized", retryable=False)
    if response.status_code == 429:
        return ModelTransportError("model_rate_limited", retryable=True)
    if 500 <= response.status_code <= 599:
        return ModelTransportError("model_unavailable", retryable=True)
    return ModelTransportError("model_http_error", retryable=False)


def _body_has_no_approved_capacity(body: bytes) -> bool:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    # OpenRouter capacity errors have varied between top-level and nested shapes.
    messages: list[str] = []
    top_level_message = parsed.get("message")
    if isinstance(top_level_message, str):
        messages.append(top_level_message)
    nested_error = parsed.get("error")
    if isinstance(nested_error, dict):
        nested_message = nested_error.get("message")
        if isinstance(nested_message, str):
            messages.append(nested_message)
    elif isinstance(nested_error, str):
        messages.append(nested_error)
    return any(
        "no endpoints found matching your data policy" in message.casefold() for message in messages
    )


def _gateway_error_from_transport(error: ModelTransportError) -> ModelGatewayError:
    if error.code == "no_approved_capacity":
        return NoApprovedCapacity("no_approved_capacity", retryable=True)
    return ModelGatewayError(error.code, retryable=error.retryable)


def _effective_max_output_tokens(budget: ModelBudget, override: TaskOverride) -> int:
    if override.max_output_tokens is None:
        return budget.max_output_tokens
    return min(budget.max_output_tokens, override.max_output_tokens)


def _estimate_payload_tokens(payload: ModelTaskPayload) -> int:
    total_chars = (
        len(payload.task)
        + len(payload.prompt_bundle_version)
        + sum(len(value) for value in payload.identifiers.values())
        + len(payload.context_role)
    )
    for excerpt in payload.excerpts:
        total_chars += len(excerpt.evidence_id)
        total_chars += len(excerpt.source_url or "")
        total_chars += len(excerpt.text)
    return math.ceil(total_chars / 4)


def _estimate_message_tokens(messages: list[dict[str, object]]) -> int:
    total_chars = 0
    for message in messages:
        content = message.get("content")
        if isinstance(content, str):
            total_chars += len(content)
    return math.ceil(total_chars / 4)


def _cost_for_tokens(input_tokens: int, output_tokens: int, route: ModelRoute) -> Decimal:
    return (
        Decimal(input_tokens) / _DECIMAL_THOUSAND * route.cost_inr_per_1k_input
        + Decimal(output_tokens) / _DECIMAL_THOUSAND * route.cost_inr_per_1k_output
    )


def _budget_breached(projected_cost: Decimal, budget: ModelBudget) -> bool:
    return (
        budget.job_cost_remaining_inr <= 0
        or projected_cost > budget.max_call_cost_inr
        or projected_cost > budget.job_cost_remaining_inr
    )


def _actual_budget_breached(cost: Decimal, budget: ModelBudget) -> bool:
    return cost > budget.max_call_cost_inr or cost > budget.job_cost_remaining_inr


def _raise_if_actual_budget_breached(cost: Decimal, budget: ModelBudget) -> None:
    if _actual_budget_breached(cost, budget):
        raise ModelBudgetExceeded("model_cost_cap_exceeded", retryable=False)


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))


def _normalise_https_url(value: str) -> str:
    split = urlsplit(value.strip())
    if split.scheme.casefold() != "https" or not split.hostname:
        raise ValueError("model source URL must use HTTPS")
    if split.username is not None or split.password is not None:
        raise ValueError("model source URL cannot contain credentials")
    try:
        port = split.port
    except ValueError as error:
        raise ValueError("model source URL port is invalid") from error
    if port is not None and port != 443:
        raise ValueError("model source URL must use the default HTTPS port")
    hostname = split.hostname.casefold().rstrip(".")
    netloc = hostname
    if port is not None:
        netloc = f"{hostname}:{port}"
    return urlunsplit(("https", netloc, split.path or "/", split.query, ""))
