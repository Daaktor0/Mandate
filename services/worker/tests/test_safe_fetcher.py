from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self

import httpx
import pytest
from mandate_worker.fetch import (
    HttpxPinnedTransport,
    PinnedRequest,
    PinnedTransportError,
    ResolvedTarget,
    SafeFetcher,
    SafeFetcherConfig,
    SafeFetchError,
    SafeFetchPolicyError,
    SafeUrlPolicy,
)
from mandate_worker.fetch import transport as transport_module

PUBLIC_IPV4 = "93.184.216.34"


@dataclass
class StaticResolver:
    answers: Sequence[str]
    calls: list[str] = field(default_factory=list)

    async def resolve(self, hostname: str) -> Sequence[str]:
        self.calls.append(hostname)
        return self.answers


@dataclass
class SequenceResolver:
    answers: list[Sequence[str]]
    calls: list[str] = field(default_factory=list)

    async def resolve(self, hostname: str) -> Sequence[str]:
        self.calls.append(hostname)
        if not self.answers:
            raise AssertionError("resolver called more often than expected")
        return self.answers.pop(0)


@dataclass
class FakeResponse:
    status_code: int = 200
    headers: Mapping[str, str] = field(
        default_factory=lambda: {"content-type": "text/html; charset=utf-8"}
    )
    chunks: tuple[bytes, ...] = (b"<html>public</html>",)

    async def _chunks(self) -> AsyncIterator[bytes]:
        for chunk in self.chunks:
            yield chunk

    def iter_raw(self) -> AsyncIterator[bytes]:
        return self._chunks()


@dataclass
class FakeTransport:
    outcomes: list[FakeResponse | PinnedTransportError]
    requests: list[PinnedRequest] = field(default_factory=list)

    @asynccontextmanager
    async def open(self, request: PinnedRequest) -> AsyncIterator[FakeResponse]:
        self.requests.append(request)
        if not self.outcomes:
            raise AssertionError("transport called more often than expected")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, PinnedTransportError):
            raise outcome
        yield outcome


class SlowTransport:
    def open(self, request: PinnedRequest) -> AbstractAsyncContextManager[FakeResponse]:
        return self._open(request)

    @asynccontextmanager
    async def _open(self, _request: PinnedRequest) -> AsyncIterator[FakeResponse]:
        await asyncio.sleep(1)
        yield FakeResponse()


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/file",
        "http://localhost/",
        "http://service.local/",
        "http://10.0.0.1/",
        "http://100.64.0.1/",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://172.16.0.1/",
        "http://192.168.0.1/",
        "http://192.0.2.1/",
        "http://224.0.0.1/",
        "http://[::1]/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[2002:0a00:0001::]/",
        "https://user:password@example.com/",
        "https://example.com/?access_token=secret",
        "https://example.com:8443/",
    ],
)
@pytest.mark.asyncio
async def test_SEC_03_policy_rejects_non_public_and_credentialed_targets(url: str) -> None:
    policy = SafeUrlPolicy(StaticResolver((PUBLIC_IPV4,)))

    with pytest.raises(SafeFetchPolicyError):
        await policy.resolve(url)


@pytest.mark.asyncio
async def test_SEC_03_policy_rejects_integer_loopback_and_mixed_dns_answers() -> None:
    integer_policy = SafeUrlPolicy(StaticResolver(("127.0.0.1",)))
    with pytest.raises(SafeFetchPolicyError, match="non_public_hostname"):
        await integer_policy.resolve("http://2130706433/")

    mixed_policy = SafeUrlPolicy(StaticResolver((PUBLIC_IPV4, "10.0.0.2")))
    with pytest.raises(SafeFetchPolicyError, match="non_public_ip_address"):
        await mixed_policy.resolve("https://mixed.example/")


@pytest.mark.asyncio
async def test_AT_INTAKE_03_SEC_03_connection_is_pinned_with_original_host_and_sni() -> None:
    resolver = StaticResolver((PUBLIC_IPV4,))
    transport = FakeTransport([FakeResponse()])
    fetcher = SafeFetcher(
        policy=SafeUrlPolicy(resolver),
        transport=transport,
        config=SafeFetcherConfig(network_attempts=1),
    )

    result = await fetcher.fetch("https://Public.Example/legal#team")

    assert result.requested_url == "https://public.example/legal"
    assert result.final_url == "https://public.example/legal"
    assert result.body == b"<html>public</html>"
    assert result.resolved_ip == PUBLIC_IPV4
    assert resolver.calls == ["public.example"]
    request = transport.requests[0]
    assert request.target.connect_url == f"https://{PUBLIC_IPV4}:443/legal"
    assert request.target.host_header == "public.example"
    assert request.target.tls_server_name == "public.example"


@pytest.mark.asyncio
async def test_SEC_03_httpx_transport_enforces_pinned_request_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport_options: dict[str, object] = {}
    client_options: dict[str, object] = {}
    stream_options: dict[str, object] = {}

    def capture_transport(**options: object) -> object:
        transport_options.update(options)
        return object()

    class CapturingResponseContext:
        async def __aenter__(self) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "text/html"})

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

    class CapturingClient:
        def __init__(self, **options: object) -> None:
            client_options.update(options)

        async def __aenter__(self) -> Self:
            return self

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc_value: BaseException | None,
            traceback: TracebackType | None,
        ) -> None:
            return None

        def stream(self, method: str, url: str, **options: object) -> CapturingResponseContext:
            stream_options.update({"method": method, "url": url, **options})
            return CapturingResponseContext()

    monkeypatch.setattr(
        "mandate_worker.fetch.transport.httpx.AsyncHTTPTransport", capture_transport
    )
    monkeypatch.setattr("mandate_worker.fetch.transport.httpx.AsyncClient", CapturingClient)
    target = ResolvedTarget(
        canonical_url="https://public.example/legal",
        scheme="https",
        hostname="public.example",
        port=443,
        request_target="/legal",
        ip_address=PUBLIC_IPV4,
    )

    async with HttpxPinnedTransport().open(
        PinnedRequest(target=target, timeout=httpx.Timeout(5.0))
    ) as response:
        assert response.status_code == 200

    assert transport_options["trust_env"] is False
    assert transport_options["retries"] == 0
    assert transport_options["http1"] is True
    assert transport_options["http2"] is False
    assert client_options["follow_redirects"] is False
    assert client_options["trust_env"] is False
    assert stream_options["method"] == "GET"
    assert stream_options["url"] == f"https://{PUBLIC_IPV4}:443/legal"
    assert stream_options["headers"] == {
        "Accept": transport_module.ACCEPTED_MEDIA,
        "Accept-Encoding": "identity",
        "Host": "public.example",
        "User-Agent": transport_module.USER_AGENT,
    }
    assert stream_options["extensions"] == {"sni_hostname": "public.example"}


@pytest.mark.asyncio
async def test_SEC_03_public_ipv6_is_bracketed_only_for_the_connection_url() -> None:
    transport = FakeTransport([FakeResponse()])
    fetcher = SafeFetcher(
        transport=transport,
        config=SafeFetcherConfig(network_attempts=1),
    )

    result = await fetcher.fetch("https://[2606:4700:4700::1111]/")

    assert result.final_url == "https://[2606:4700:4700::1111]/"
    assert transport.requests[0].target.connect_url == "https://[2606:4700:4700::1111]:443/"
    assert transport.requests[0].target.host_header == "[2606:4700:4700::1111]"


@pytest.mark.asyncio
async def test_ER_11_SEC_03_redirect_to_private_ip_is_blocked_before_second_request() -> None:
    transport = FakeTransport(
        [FakeResponse(status_code=302, headers={"location": "http://10.0.0.5/admin"})]
    )
    fetcher = SafeFetcher(
        policy=SafeUrlPolicy(StaticResolver((PUBLIC_IPV4,))),
        transport=transport,
        config=SafeFetcherConfig(network_attempts=1),
    )

    with pytest.raises(SafeFetchError, match="non_public_ip_address"):
        await fetcher.fetch("https://public.example/")
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_SEC_03_same_host_redirect_is_reresolved_and_rebinding_is_blocked() -> None:
    resolver = SequenceResolver([(PUBLIC_IPV4,), ("127.0.0.1",)])
    transport = FakeTransport([FakeResponse(status_code=302, headers={"location": "/privacy"})])
    fetcher = SafeFetcher(
        policy=SafeUrlPolicy(resolver),
        transport=transport,
        config=SafeFetcherConfig(network_attempts=1),
    )

    with pytest.raises(SafeFetchError, match="non_public_ip_address"):
        await fetcher.fetch("https://public.example/")
    assert resolver.calls == ["public.example", "public.example"]
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_SEC_03_retry_reresolves_and_never_uses_a_rebound_private_answer() -> None:
    resolver = SequenceResolver([(PUBLIC_IPV4,), ("127.0.0.1",)])
    transport = FakeTransport([PinnedTransportError("fixture failure")])
    fetcher = SafeFetcher(
        policy=SafeUrlPolicy(resolver),
        transport=transport,
        config=SafeFetcherConfig(network_attempts=2),
    )

    with pytest.raises(SafeFetchError, match="non_public_ip_address"):
        await fetcher.fetch("https://public.example/")
    assert len(transport.requests) == 1


@pytest.mark.asyncio
async def test_SEC_03_redirect_budget_is_capped_at_five() -> None:
    redirects: list[FakeResponse | PinnedTransportError] = [
        FakeResponse(status_code=302, headers={"location": f"/redirect-{index}"})
        for index in range(6)
    ]
    transport = FakeTransport(redirects)
    fetcher = SafeFetcher(
        policy=SafeUrlPolicy(StaticResolver((PUBLIC_IPV4,))),
        transport=transport,
        config=SafeFetcherConfig(network_attempts=1),
    )

    with pytest.raises(SafeFetchError, match="too_many_redirects"):
        await fetcher.fetch("https://public.example/")
    assert len(transport.requests) == 6


@pytest.mark.parametrize(
    ("response", "error_code"),
    [
        (FakeResponse(headers={}), "content_type_not_allowed"),
        (
            FakeResponse(headers={"content-type": "application/octet-stream"}),
            "content_type_not_allowed",
        ),
        (
            FakeResponse(headers={"content-type": "text/html", "content-encoding": "gzip"}),
            "content_encoding_not_allowed",
        ),
        (
            FakeResponse(headers={"content-type": "text/html", "content-length": "9"}),
            "response_too_large",
        ),
        (
            FakeResponse(headers={"content-type": "text/html"}, chunks=(b"1234", b"5678")),
            "response_too_large",
        ),
    ],
)
@pytest.mark.asyncio
async def test_SEC_03_response_policy_is_bounded(
    response: FakeResponse,
    error_code: str,
) -> None:
    fetcher = SafeFetcher(
        policy=SafeUrlPolicy(StaticResolver((PUBLIC_IPV4,))),
        transport=FakeTransport([response]),
        config=SafeFetcherConfig(max_response_bytes=7, network_attempts=1),
    )

    with pytest.raises(SafeFetchError, match=error_code):
        await fetcher.fetch("https://public.example/")


@pytest.mark.asyncio
async def test_SEC_03_total_timeout_is_bounded_and_retryable() -> None:
    fetcher = SafeFetcher(
        policy=SafeUrlPolicy(StaticResolver((PUBLIC_IPV4,))),
        transport=SlowTransport(),
        config=SafeFetcherConfig(total_timeout_seconds=0.01, network_attempts=1),
    )

    with pytest.raises(SafeFetchError, match="fetch_timeout") as captured:
        await fetcher.fetch("https://public.example/")
    assert captured.value.retryable is True


def test_SEC_03_config_rejects_relaxed_security_caps() -> None:
    with pytest.raises(ValueError):
        SafeFetcherConfig(max_redirects=6)
    with pytest.raises(ValueError):
        SafeFetcherConfig(max_response_bytes=10 * 1024 * 1024 + 1)
    with pytest.raises(ValueError):
        SafeFetcherConfig(network_attempts=3)
