"""FastAPI control surface for the Mandate worker."""

from __future__ import annotations

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict
from starlette.middleware.base import RequestResponseEndpoint

from mandate_worker import __version__
from mandate_worker.observability import (
    configure_logging,
    get_logger,
    normalise_trace_id,
    trace_context,
)

TRACE_HEADER = "X-Trace-Id"


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    service: str
    version: str


def create_app(service_name: str = "mandate-worker") -> FastAPI:
    """Create an internal service API without starting external providers."""

    configure_logging()
    application = FastAPI(
        title=service_name,
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    logger = get_logger()

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
