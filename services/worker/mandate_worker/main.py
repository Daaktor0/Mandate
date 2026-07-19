from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict
from starlette.middleware.base import RequestResponseEndpoint

from mandate_worker import __version__
from mandate_worker.composition import (
    LightTaskDependenciesFactory,
    LightTaskRuntime,
    start_light_task_runtime,
)
from mandate_worker.fixtures import AdapterCapability
from mandate_worker.observability import (
    configure_logging,
    get_logger,
    normalise_trace_id,
    trace_context,
)
from mandate_worker.runtime import RuntimeConfigurationError, build_runtime_adapter_plan

TRACE_HEADER = "X-Trace-Id"


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    service: str
    version: str


def create_app(
    service_name: str = "mandate-worker",
    *,
    environ: Mapping[str, str] | None = None,
    fixture_root: Path | None = None,
    light_task_dependencies_factory: LightTaskDependenciesFactory | None = None,
) -> FastAPI:
    """Create an internal service API without starting external providers."""

    configure_logging()
    logger = get_logger()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        light_task_runtime: LightTaskRuntime | None = None
        application.state.light_task_runtime = None
        application.state.light_task_loop_tasks = ()
        if service_name == "mandate-worker":
            light_task_runtime = start_light_task_runtime(
                environ=environ,
                dependencies_factory=light_task_dependencies_factory,
            )
            application.state.light_task_runtime = light_task_runtime
            application.state.light_task_runtime_configuration = light_task_runtime.configuration
            application.state.light_task_loop_tasks = light_task_runtime.tasks
            logger.info(
                "light_task_runtime_configured",
                enabled=light_task_runtime.configuration.enabled,
                queue_backend=light_task_runtime.configuration.queue_backend,
                requested_queue_backend=light_task_runtime.configuration.requested_queue_backend,
                task_count=len(light_task_runtime.tasks),
            )
        try:
            yield
        finally:
            if light_task_runtime is not None:
                await light_task_runtime.stop()
                application.state.light_task_loop_tasks = light_task_runtime.tasks

    application = FastAPI(
        title=service_name,
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    if service_name == "mandate-worker":
        runtime_plan = build_runtime_adapter_plan(environ=environ, fixture_root=fixture_root)
        if (
            not runtime_plan.demo_mode
            and runtime_plan.bindings[AdapterCapability.COMPANY_DATA] == "attestr"
        ):
            raise RuntimeConfigurationError(
                "PROVIDER_COMPANY_DATA=attestr is disabled because the required "
                "company-master-data capability has not been verified"
            )
        application.state.runtime_adapter_plan = runtime_plan
        logger.info(
            "runtime_configured",
            demo_mode=runtime_plan.demo_mode,
            zero_spend=runtime_plan.zero_spend,
            fixture_revision=runtime_plan.fixture_revision,
            adapter_backends={
                capability.value: backend for capability, backend in runtime_plan.bindings.items()
            },
            overridden_selectors=runtime_plan.overridden_selectors,
        )

    @application.middleware("http")
    async def trace_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
        trace_id = normalise_trace_id(request.headers.get(TRACE_HEADER))
        with trace_context(trace_id, http_path=request.url.path):
            response = await call_next(request)
            response.headers[TRACE_HEADER] = trace_id
            return response

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        logger.info("health_check", status="ok")
        return HealthResponse(
            status="ok",
            service=service_name,
            version=__version__,
        )

    return application


app = create_app()
