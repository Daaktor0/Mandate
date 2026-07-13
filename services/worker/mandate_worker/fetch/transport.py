"""HTTP transport that connects only to a SafeUrlPolicy-vetted IP."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

import httpx

from .policy import ResolvedTarget

USER_AGENT = "Mandate-SafeFetcher/1.0 (+public-information-research)"
ACCEPTED_MEDIA = (
    "text/html,application/xhtml+xml,application/pdf,text/plain,application/xml,text/xml"
)


class PinnedTransportError(RuntimeError):
    """The pinned network request failed without exposing raw details."""


@dataclass(frozen=True, slots=True)
class PinnedRequest:
    target: ResolvedTarget
    timeout: httpx.Timeout


class PinnedResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def iter_raw(self) -> AsyncIterator[bytes]:
        """Stream undecoded bytes from the response."""


class PinnedTransport(Protocol):
    def open(self, request: PinnedRequest) -> AbstractAsyncContextManager[PinnedResponse]:
        """Open one request to the exact target IP."""


class _HttpxPinnedResponse:
    def __init__(self, response: httpx.Response) -> None:
        self.status_code = response.status_code
        self.headers: Mapping[str, str] = response.headers
        self._response = response

    def iter_raw(self) -> AsyncIterator[bytes]:
        return self._response.aiter_raw()


class HttpxPinnedTransport:
    """Create an isolated no-proxy connection for every vetted URL hop."""

    @asynccontextmanager
    async def open(self, request: PinnedRequest) -> AsyncIterator[PinnedResponse]:
        target = request.target
        transport = httpx.AsyncHTTPTransport(
            trust_env=False,
            retries=0,
            http1=True,
            http2=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        )
        headers = {
            "Accept": ACCEPTED_MEDIA,
            "Accept-Encoding": "identity",
            "Host": target.host_header,
            "User-Agent": USER_AGENT,
        }
        extensions: dict[str, object] = {}
        if target.tls_server_name is not None:
            extensions["sni_hostname"] = target.tls_server_name

        try:
            async with httpx.AsyncClient(
                transport=transport,
                follow_redirects=False,
                trust_env=False,
                timeout=request.timeout,
            ) as client:
                async with client.stream(
                    "GET",
                    target.connect_url,
                    headers=headers,
                    extensions=extensions,
                ) as response:
                    yield _HttpxPinnedResponse(response)
        except httpx.TransportError as error:
            raise PinnedTransportError("pinned_transport_failed") from error
