"""Bounded public-information retrieval through the pinned-IP transport."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from .policy import SafeFetchPolicyError, SafeUrlPolicy, canonicalize_url
from .transport import HttpxPinnedTransport, PinnedRequest, PinnedTransport, PinnedTransportError

REDIRECT_STATUSES = {301, 302, 303, 307, 308}
ALLOWED_CONTENT_TYPES = frozenset(
    {
        "application/pdf",
        "application/xhtml+xml",
        "application/xml",
        "text/html",
        "text/plain",
        "text/xml",
    }
)


class SafeFetchError(RuntimeError):
    """A stable, audit-safe fetch failure."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class SafeFetchResult:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    body: bytes
    redirect_chain: tuple[str, ...]
    resolved_ip: str


@dataclass(frozen=True, slots=True)
class SafeFetcherConfig:
    max_redirects: int = 5
    max_response_bytes: int = 10 * 1024 * 1024
    total_timeout_seconds: float = 20.0
    connect_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 10.0
    network_attempts: int = 2

    def __post_init__(self) -> None:
        if not 0 <= self.max_redirects <= 5:
            raise ValueError("max_redirects must be between 0 and 5")
        if not 1 <= self.max_response_bytes <= 10 * 1024 * 1024:
            raise ValueError("max_response_bytes must be between 1 and 10 MiB")
        if not 1 <= self.network_attempts <= 2:
            raise ValueError("network_attempts must be 1 or 2")
        for timeout in (
            self.total_timeout_seconds,
            self.connect_timeout_seconds,
            self.read_timeout_seconds,
        ):
            if timeout <= 0:
                raise ValueError("fetch timeouts must be positive")


def _content_type(headers: Mapping[str, str]) -> str:
    raw = headers.get("content-type", "")
    content_type = raw.split(";", maxsplit=1)[0].strip().lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise SafeFetchError("content_type_not_allowed")
    return content_type


def _validate_content_encoding(headers: Mapping[str, str]) -> None:
    encoding = headers.get("content-encoding", "identity").strip().lower()
    if encoding not in {"", "identity"}:
        raise SafeFetchError("content_encoding_not_allowed")


def _validate_declared_length(headers: Mapping[str, str], maximum: int) -> None:
    raw = headers.get("content-length")
    if raw is None:
        return
    try:
        length = int(raw)
    except ValueError as error:
        raise SafeFetchError("invalid_content_length") from error
    if length < 0 or length > maximum:
        raise SafeFetchError("response_too_large")


class SafeFetcher:
    """Fetch HTTP(S) content without allowing DNS or redirect policy bypass."""

    def __init__(
        self,
        *,
        policy: SafeUrlPolicy | None = None,
        transport: PinnedTransport | None = None,
        config: SafeFetcherConfig | None = None,
    ) -> None:
        self._policy = policy or SafeUrlPolicy()
        self._transport = transport or HttpxPinnedTransport()
        self._config = config or SafeFetcherConfig()

    async def fetch(self, url: str) -> SafeFetchResult:
        try:
            async with asyncio.timeout(self._config.total_timeout_seconds):
                return await self._fetch_within_budget(url)
        except TimeoutError as error:
            raise SafeFetchError("fetch_timeout", retryable=True) from error
        except SafeFetchPolicyError as error:
            raise SafeFetchError(error.code) from error

    async def _fetch_within_budget(self, url: str) -> SafeFetchResult:
        requested_url: str | None = None
        current_url = url
        redirect_chain: list[str] = []

        while True:
            target = None
            response_data: tuple[int, Mapping[str, str], bytes] | None = None
            last_transport_error: PinnedTransportError | None = None

            for _attempt in range(self._config.network_attempts):
                target = await self._policy.resolve(current_url)
                if requested_url is None:
                    requested_url = target.canonical_url
                timeout = httpx.Timeout(
                    connect=self._config.connect_timeout_seconds,
                    read=self._config.read_timeout_seconds,
                    write=self._config.connect_timeout_seconds,
                    pool=self._config.connect_timeout_seconds,
                )
                try:
                    async with self._transport.open(
                        PinnedRequest(target=target, timeout=timeout)
                    ) as response:
                        if response.status_code in REDIRECT_STATUSES:
                            response_data = (response.status_code, response.headers, b"")
                        else:
                            content_type = _content_type(response.headers)
                            _validate_content_encoding(response.headers)
                            _validate_declared_length(
                                response.headers, self._config.max_response_bytes
                            )
                            body = bytearray()
                            async for chunk in response.iter_raw():
                                if len(body) + len(chunk) > self._config.max_response_bytes:
                                    raise SafeFetchError("response_too_large")
                                body.extend(chunk)
                            response_data = (response.status_code, response.headers, bytes(body))
                            return SafeFetchResult(
                                requested_url=requested_url,
                                final_url=target.canonical_url,
                                status_code=response.status_code,
                                content_type=content_type,
                                body=bytes(body),
                                redirect_chain=tuple(redirect_chain),
                                resolved_ip=target.ip_address,
                            )
                    break
                except PinnedTransportError as error:
                    last_transport_error = error
                    continue

            if response_data is None:
                raise SafeFetchError("transport_failed", retryable=True) from last_transport_error
            if target is None:  # pragma: no cover - loop/config invariant
                raise RuntimeError("fetch target missing")

            _status, headers, _body = response_data
            location = headers.get("location")
            if location is None or not location.strip():
                raise SafeFetchError("redirect_without_location")
            if len(redirect_chain) >= self._config.max_redirects:
                raise SafeFetchError("too_many_redirects")
            current_url = canonicalize_url(urljoin(target.canonical_url, location.strip()))[0]
            redirect_chain.append(current_url)
