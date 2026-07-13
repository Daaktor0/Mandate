"""URL canonicalisation, DNS vetting and IP pinning for outbound retrieval."""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qsl, urlsplit, urlunsplit

ALLOWED_PORTS = {"http": 80, "https": 443}
BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")
HOST_LABEL = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
CREDENTIAL_QUERY_KEY = re.compile(
    r"(?:^|[-_.])(auth|code|credential|jwt|key|password|secret|session|sig|signature|token)"
    r"(?:$|[-_.])",
    re.IGNORECASE,
)
MAX_RESOLVED_ADDRESSES = 16
IPV6_TRANSLATION_NETWORKS = (
    ipaddress.IPv6Network("64:ff9b::/96"),
    ipaddress.IPv6Network("64:ff9b:1::/48"),
)


class SafeFetchPolicyError(ValueError):
    """A target cannot be fetched without weakening the SSRF boundary."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class HostResolver(Protocol):
    async def resolve(self, hostname: str) -> Sequence[str]:
        """Return every address in one DNS resolution result."""


class SystemHostResolver:
    """Resolve with the event loop's non-blocking system resolver."""

    async def resolve(self, hostname: str) -> Sequence[str]:
        loop = asyncio.get_running_loop()
        try:
            answers = await loop.getaddrinfo(
                hostname,
                None,
                family=socket.AF_UNSPEC,
                type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            )
        except OSError as error:
            raise SafeFetchPolicyError("dns_resolution_failed") from error
        return tuple(str(answer[4][0]) for answer in answers)


@dataclass(frozen=True, slots=True)
class ResolvedTarget:
    """One URL hop bound to an already-vetted connection address."""

    canonical_url: str
    scheme: str
    hostname: str
    port: int
    request_target: str
    ip_address: str

    @property
    def host_header(self) -> str:
        return f"[{self.hostname}]" if ":" in self.hostname else self.hostname

    @property
    def connect_url(self) -> str:
        address = f"[{self.ip_address}]" if ":" in self.ip_address else self.ip_address
        return f"{self.scheme}://{address}:{self.port}{self.request_target}"

    @property
    def tls_server_name(self) -> str | None:
        return self.hostname if self.scheme == "https" else None


def _public_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise SafeFetchPolicyError("invalid_ip_address") from error

    if isinstance(address, ipaddress.IPv6Address):
        if (
            address.scope_id is not None
            or address.ipv4_mapped is not None
            or address.sixtofour is not None
            or address.teredo is not None
            or any(address in network for network in IPV6_TRANSLATION_NETWORKS)
        ):
            raise SafeFetchPolicyError("non_public_ip_address")
    # ``ipaddress.is_global`` is deliberately broader than an Internet-routable
    # unicast policy (for example, Python reports IPv4 multicast as global).
    # SafeFetcher only connects to ordinary public unicast addresses.
    if address.is_multicast or address.is_unspecified or not address.is_global:
        raise SafeFetchPolicyError("non_public_ip_address")
    return address


def _canonical_hostname(raw_hostname: str) -> str:
    hostname = raw_hostname.rstrip(".").lower()
    try:
        return str(ipaddress.ip_address(hostname))
    except ValueError:
        pass

    try:
        hostname = hostname.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise SafeFetchPolicyError("invalid_hostname") from error
    if (
        not hostname
        or len(hostname) > 253
        or hostname == "localhost"
        or hostname.endswith(BLOCKED_HOST_SUFFIXES)
        or "." not in hostname
        or not all(HOST_LABEL.fullmatch(label) for label in hostname.split("."))
    ):
        raise SafeFetchPolicyError("non_public_hostname")
    return hostname


def canonicalize_url(value: str) -> tuple[str, str, str, int, str]:
    """Return canonical URL parts without resolving or making a request."""

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise SafeFetchPolicyError("malformed_url") from error

    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_PORTS:
        raise SafeFetchPolicyError("unsupported_scheme")
    if parsed.username is not None or parsed.password is not None:
        raise SafeFetchPolicyError("credentials_forbidden")
    if parsed.hostname is None:
        raise SafeFetchPolicyError("invalid_hostname")
    expected_port = ALLOWED_PORTS[scheme]
    if port is not None and port != expected_port:
        raise SafeFetchPolicyError("unsupported_port")
    for key, _value in parse_qsl(parsed.query, keep_blank_values=True):
        if CREDENTIAL_QUERY_KEY.search(key):
            raise SafeFetchPolicyError("credentials_forbidden")

    hostname = _canonical_hostname(parsed.hostname)
    effective_port = port or expected_port
    request_path = parsed.path or "/"
    request_target = request_path + (f"?{parsed.query}" if parsed.query else "")
    netloc = f"[{hostname}]" if ":" in hostname else hostname
    canonical_url = urlunsplit((scheme, netloc, request_path, parsed.query, ""))
    return canonical_url, scheme, hostname, effective_port, request_target


class SafeUrlPolicy:
    """Resolve a canonical URL and fail closed on every non-public answer."""

    def __init__(self, resolver: HostResolver | None = None) -> None:
        self._resolver = resolver or SystemHostResolver()

    async def resolve(self, value: str) -> ResolvedTarget:
        canonical_url, scheme, hostname, port, request_target = canonicalize_url(value)
        try:
            direct_address = ipaddress.ip_address(hostname)
        except ValueError:
            raw_addresses = await self._resolver.resolve(hostname)
        else:
            raw_addresses = (str(direct_address),)

        unique_addresses = tuple(dict.fromkeys(raw_addresses))
        if not unique_addresses:
            raise SafeFetchPolicyError("dns_resolution_failed")
        if len(unique_addresses) > MAX_RESOLVED_ADDRESSES:
            raise SafeFetchPolicyError("too_many_dns_answers")

        vetted = tuple(_public_ip(address) for address in unique_addresses)
        return ResolvedTarget(
            canonical_url=canonical_url,
            scheme=scheme,
            hostname=hostname,
            port=port,
            request_target=request_target,
            ip_address=str(vetted[0]),
        )
