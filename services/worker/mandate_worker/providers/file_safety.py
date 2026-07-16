"""Malware, archive and sandbox-parser gate for untrusted filing binaries.

No PDF or ZIP may yield text until its bytes match the quarantined reference, a
malware scanner returns a clean verdict, archive limits pass and a parser attests
to the networkless read-only sandbox profile. Parsed text remains untrusted and
is not admitted as Evidence by this module.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import stat
import struct
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from io import BytesIO
from pathlib import Path
from typing import Final, Literal, Protocol, Self
from zipfile import BadZipFile, LargeZipFile, ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from mandate_worker.fixtures import AdapterCapability, FixtureCatalog
from mandate_worker.runtime import RuntimeAdapterPlan

from .corporate_filings import CorporateFilingReference

MAX_BINARY_BYTES: Final = 25 * 1024 * 1024
MAX_ARCHIVE_MEMBERS: Final = 50
MAX_ARCHIVE_MEMBER_BYTES: Final = 25 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES: Final = 100 * 1024 * 1024
MAX_ARCHIVE_COMPRESSION_RATIO: Final = 100.0
MAX_ARCHIVE_MEMBER_NAME: Final = 240
MAX_PDF_PAGES: Final = 500
MAX_PARSED_CHARACTERS: Final = 2_000_000
MAX_CLAMD_REPLY_BYTES: Final = 4_096
PDF_MAGIC: Final = b"%PDF-"
ZIP_MAGICS: Final = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
ALLOWED_ZIP_COMPRESSION: Final = frozenset({ZIP_STORED, ZIP_DEFLATED})
SANDBOX_PROFILE: Literal["networkless_readonly_v1"] = "networkless_readonly_v1"


class FileSafetyError(RuntimeError):
    """Stable file-safety failure that never includes document bytes or source paths."""

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(code)


class FileSafetyConfigurationError(RuntimeError):
    """A scanner or parser binding is absent, malformed or unsafe."""


class MalwareVerdict(StrEnum):
    CLEAN = "clean"
    INFECTED = "infected"


class MalwareScanResult(BaseModel):
    """Audit-safe scanner result; raw scanner output is deliberately excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]+$")
    verdict: MalwareVerdict
    scanned_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    threat_name: str | None = Field(default=None, min_length=1, max_length=200)
    engine_version: str | None = Field(default=None, min_length=1, max_length=100)
    signature_version: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_verdict_shape(self) -> Self:
        if self.verdict is MalwareVerdict.CLEAN and self.threat_name is not None:
            raise ValueError("clean malware result cannot contain a threat name")
        if self.verdict is MalwareVerdict.INFECTED and self.threat_name is None:
            raise ValueError("infected malware result requires a threat name")
        return self


class MalwareScanner(Protocol):
    async def scan(self, body: bytes) -> MalwareScanResult:
        """Scan bounded bytes without returning or logging them."""


class ClamdTransport(Protocol):
    async def scan_stream(self, body: bytes) -> str:
        """Return one bounded clamd INSTREAM reply."""


@dataclass(frozen=True, slots=True)
class UnixClamdTransport:
    """Local Unix-socket clamd INSTREAM transport with no shell or file path exposure."""

    socket_path: Path
    timeout_seconds: float = 20.0
    chunk_size: int = 64 * 1024

    def __post_init__(self) -> None:
        if not self.socket_path.is_absolute():
            raise FileSafetyConfigurationError("clamd_socket_must_be_absolute")
        if not 0 < self.timeout_seconds <= 60:
            raise FileSafetyConfigurationError("clamd_timeout_invalid")
        if not 1 <= self.chunk_size <= 1024 * 1024:
            raise FileSafetyConfigurationError("clamd_chunk_size_invalid")

    async def scan_stream(self, body: bytes) -> str:
        writer: asyncio.StreamWriter | None = None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                reader, writer = await asyncio.open_unix_connection(str(self.socket_path))
                writer.write(b"zINSTREAM\0")
                for offset in range(0, len(body), self.chunk_size):
                    chunk = body[offset : offset + self.chunk_size]
                    writer.write(struct.pack(">I", len(chunk)))
                    writer.write(chunk)
                writer.write(struct.pack(">I", 0))
                await writer.drain()
                reply = await reader.readuntil(b"\0")
        except (OSError, TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as error:
            raise FileSafetyError("malware_scanner_unavailable", retryable=True) from error
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass
        if len(reply) > MAX_CLAMD_REPLY_BYTES:
            raise FileSafetyError("malware_scanner_reply_too_large")
        return reply.rstrip(b"\0").decode("utf-8", errors="replace")


@dataclass(frozen=True, slots=True)
class ClamdMalwareScanner:
    """ClamAV scanner using the documented clamd INSTREAM protocol."""

    transport: ClamdTransport

    async def scan(self, body: bytes) -> MalwareScanResult:
        _validate_body(body)
        digest = hashlib.sha256(body).hexdigest()
        reply = (await self.transport.scan_stream(body)).strip()
        if reply.endswith(": OK"):
            return MalwareScanResult(
                provider="clamd",
                verdict=MalwareVerdict.CLEAN,
                scanned_sha256=digest,
            )
        if reply.endswith(" FOUND") and ": " in reply:
            threat_name = reply.rsplit(": ", 1)[1].removesuffix(" FOUND").strip()
            if not threat_name:
                raise FileSafetyError("malware_scanner_reply_invalid")
            return MalwareScanResult(
                provider="clamd",
                verdict=MalwareVerdict.INFECTED,
                scanned_sha256=digest,
                threat_name=threat_name[:200],
            )
        if reply.endswith(" ERROR"):
            raise FileSafetyError("malware_scanner_error", retryable=True)
        raise FileSafetyError("malware_scanner_reply_invalid")


@dataclass(frozen=True, slots=True)
class FixtureMalwareScanner:
    """Hash-allowlisted deterministic scanner for zero-spend demo mode."""

    clean_sha256s: frozenset[str]
    infected_sha256s: Mapping[str, str]
    engine_version: str
    signature_version: str

    async def scan(self, body: bytes) -> MalwareScanResult:
        _validate_body(body)
        digest = hashlib.sha256(body).hexdigest()
        threat_name = self.infected_sha256s.get(digest)
        if threat_name is not None:
            return MalwareScanResult(
                provider="fixture",
                verdict=MalwareVerdict.INFECTED,
                scanned_sha256=digest,
                threat_name=threat_name,
                engine_version=self.engine_version,
                signature_version=self.signature_version,
            )
        if digest not in self.clean_sha256s:
            raise FileSafetyError("malware_fixture_missing")
        return MalwareScanResult(
            provider="fixture",
            verdict=MalwareVerdict.CLEAN,
            scanned_sha256=digest,
            engine_version=self.engine_version,
            signature_version=self.signature_version,
        )


class SandboxParseResult(BaseModel):
    """Attested text-only result from the isolated PDF parser boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parser: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]+$")
    parser_version: str = Field(min_length=1, max_length=100)
    sandbox_profile: Literal["networkless_readonly_v1"] = SANDBOX_PROFILE
    network_disabled: Literal[True] = True
    read_only_filesystem: Literal[True] = True
    active_content_removed: Literal[True] = True
    page_count: int = Field(ge=1, le=MAX_PDF_PAGES)
    text: str = Field(min_length=1, max_length=MAX_PARSED_CHARACTERS)
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_text_digest(self) -> Self:
        digest = hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(digest, self.text_sha256):
            raise ValueError("parsed text digest mismatch")
        return self


class SandboxPdfParser(Protocol):
    async def parse_pdf(self, body: bytes, *, source_sha256: str) -> SandboxParseResult:
        """Parse one scanned PDF inside the networkless read-only sandbox."""


@dataclass(frozen=True, slots=True)
class FixtureSandboxPdfParser:
    """Deterministic parser replay for demo mode; performs no real PDF parsing."""

    documents: Mapping[str, tuple[int, str]] = field(repr=False)
    parser_version: str

    async def parse_pdf(self, body: bytes, *, source_sha256: str) -> SandboxParseResult:
        _validate_pdf(body)
        digest = hashlib.sha256(body).hexdigest()
        if not hmac.compare_digest(digest, source_sha256):
            raise FileSafetyError("sandbox_parser_source_mismatch")
        fixture = self.documents.get(digest)
        if fixture is None:
            raise FileSafetyError("sandbox_parser_fixture_missing")
        page_count, text = fixture
        return SandboxParseResult(
            source_sha256=digest,
            parser="fixture",
            parser_version=self.parser_version,
            page_count=page_count,
            text=text,
            text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        )


class SafeParsedDocument(BaseModel):
    """Text unlocked by the complete file-safety gate, but not admitted as evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(min_length=1, max_length=300)
    source_name: str = Field(min_length=1, max_length=MAX_ARCHIVE_MEMBER_NAME)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parser: str = Field(min_length=1, max_length=64)
    parser_version: str = Field(min_length=1, max_length=100)
    page_count: int = Field(ge=1, le=MAX_PDF_PAGES)
    text: str = Field(min_length=1, max_length=MAX_PARSED_CHARACTERS)
    text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    parse_allowed: Literal[True] = True
    untrusted: Literal[True] = True
    evidence_admitted: Literal[False] = False


class FileSafetyResult(BaseModel):
    """Audit-safe result containing no binary bytes or scanner raw output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_document_id: str = Field(min_length=1, max_length=128)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    malware_scans: tuple[MalwareScanResult, ...] = Field(min_length=1, max_length=51)
    documents: tuple[SafeParsedDocument, ...] = Field(min_length=1, max_length=MAX_ARCHIVE_MEMBERS)
    parse_allowed: Literal[True] = True
    evidence_admitted: Literal[False] = False


@dataclass(frozen=True, slots=True)
class QuarantinedBinary:
    """Reference and bytes paired without making bytes printable or serialisable."""

    reference: CorporateFilingReference
    body: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _validate_body(self.body)
        if self.reference.quarantine_status != "pending_malware_scan":
            raise FileSafetyError("file_not_quarantined")
        if self.reference.parse_allowed is not False:
            raise FileSafetyError("file_already_parseable")
        if len(self.body) != self.reference.size_bytes:
            raise FileSafetyError("file_size_mismatch")
        digest = hashlib.sha256(self.body).hexdigest()
        if not hmac.compare_digest(digest, self.reference.sha256):
            raise FileSafetyError("file_digest_mismatch")


@dataclass(frozen=True, slots=True)
class _ParseCandidate:
    document_id: str
    source_name: str
    body: bytes = field(repr=False)
    sha256: str


@dataclass(frozen=True, slots=True)
class FileSafetyPipeline:
    """Mandatory sequence: quarantine integrity → scan → archive limits → sandbox parse."""

    scanner: MalwareScanner
    parser: SandboxPdfParser

    async def process(
        self,
        reference: CorporateFilingReference,
        body: bytes,
    ) -> FileSafetyResult:
        quarantined = QuarantinedBinary(reference=reference, body=body)
        outer_scan = await self.scanner.scan(quarantined.body)
        _require_clean_scan(outer_scan, reference.sha256)

        candidates = _expand_candidates(reference, quarantined.body)
        scans: list[MalwareScanResult] = [outer_scan]
        documents: list[SafeParsedDocument] = []
        for candidate in candidates:
            if not hmac.compare_digest(candidate.sha256, reference.sha256):
                member_scan = await self.scanner.scan(candidate.body)
                _require_clean_scan(member_scan, candidate.sha256)
                scans.append(member_scan)
            parsed = await self.parser.parse_pdf(
                candidate.body,
                source_sha256=candidate.sha256,
            )
            _validate_parser_attestation(parsed, candidate.sha256)
            documents.append(
                SafeParsedDocument(
                    document_id=candidate.document_id,
                    source_name=candidate.source_name,
                    source_sha256=candidate.sha256,
                    parser=parsed.parser,
                    parser_version=parsed.parser_version,
                    page_count=parsed.page_count,
                    text=parsed.text,
                    text_sha256=parsed.text_sha256,
                )
            )

        return FileSafetyResult(
            source_document_id=reference.document_id,
            source_sha256=reference.sha256,
            malware_scans=tuple(scans),
            documents=tuple(documents),
        )


class _MalwareFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    fixture_version: Literal[1] = Field(alias="fixtureVersion")
    engine_version: str = Field(alias="engineVersion", min_length=1, max_length=100)
    signature_version: str = Field(alias="signatureVersion", min_length=1, max_length=100)
    clean_sha256s: frozenset[str] = Field(alias="cleanSha256s", min_length=1)
    infected_sha256s: dict[str, str] = Field(alias="infectedSha256s")

    @model_validator(mode="after")
    def validate_hashes(self) -> Self:
        all_hashes = self.clean_sha256s | set(self.infected_sha256s)
        if any(len(value) != 64 or any(character not in "0123456789abcdef" for character in value) for value in all_hashes):
            raise ValueError("malware fixture contains an invalid SHA-256")
        if self.clean_sha256s & set(self.infected_sha256s):
            raise ValueError("malware fixture hashes cannot be both clean and infected")
        if any(not value or len(value) > 200 for value in self.infected_sha256s.values()):
            raise ValueError("malware fixture threat name is invalid")
        return self


class _ParserFixtureDocument(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    page_count: int = Field(alias="pageCount", ge=1, le=MAX_PDF_PAGES)
    text: str = Field(min_length=1, max_length=MAX_PARSED_CHARACTERS)


class _ParserFixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    fixture_version: Literal[1] = Field(alias="fixtureVersion")
    sandbox_profile: Literal["networkless_readonly_v1"] = Field(alias="sandboxProfile")
    parser_version: str = Field(alias="parserVersion", min_length=1, max_length=100)
    documents: tuple[_ParserFixtureDocument, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def document_hashes_must_be_unique(self) -> Self:
        hashes = [document.sha256 for document in self.documents]
        if len(hashes) != len(set(hashes)):
            raise ValueError("parser fixture document hashes must be unique")
        return self


def build_malware_scanner(
    plan: RuntimeAdapterPlan,
    *,
    environ: Mapping[str, str] | None = None,
    clamd_transport: ClamdTransport | None = None,
) -> MalwareScanner:
    """Build an allowlisted scanner without fixture or clean-verdict fallback."""

    binding = plan.bindings[AdapterCapability.MALWARE_SCANNER]
    if binding == "fixture":
        if not plan.demo_mode or plan.catalog is None:
            raise FileSafetyConfigurationError("malware_fixture_requires_demo_mode")
        try:
            fixture = _MalwareFixture.model_validate(
                plan.catalog.payload(AdapterCapability.MALWARE_SCANNER)
            )
        except (KeyError, ValidationError, ValueError) as error:
            raise FileSafetyConfigurationError("malware_fixture_invalid") from error
        return FixtureMalwareScanner(
            clean_sha256s=fixture.clean_sha256s,
            infected_sha256s=fixture.infected_sha256s,
            engine_version=fixture.engine_version,
            signature_version=fixture.signature_version,
        )
    if binding == "clamd_unix":
        if clamd_transport is None:
            environment = os.environ if environ is None else environ
            raw_socket = environment.get("CLAMD_SOCKET_PATH", "").strip()
            if not raw_socket:
                raise FileSafetyConfigurationError("clamd_socket_missing")
            clamd_transport = UnixClamdTransport(Path(raw_socket))
        return ClamdMalwareScanner(clamd_transport)
    if binding == "unconfigured":
        raise FileSafetyConfigurationError("malware_scanner_unconfigured")
    raise FileSafetyConfigurationError("malware_scanner_not_allowlisted")


def build_sandbox_pdf_parser(plan: RuntimeAdapterPlan) -> SandboxPdfParser:
    """Build the parser boundary; live parsing remains disabled until isolated deployment."""

    binding = plan.bindings[AdapterCapability.FILE_PARSER]
    if binding == "fixture":
        if not plan.demo_mode or plan.catalog is None:
            raise FileSafetyConfigurationError("file_parser_fixture_requires_demo_mode")
        try:
            fixture = _ParserFixture.model_validate(
                plan.catalog.payload(AdapterCapability.FILE_PARSER)
            )
        except (KeyError, ValidationError, ValueError) as error:
            raise FileSafetyConfigurationError("file_parser_fixture_invalid") from error
        return FixtureSandboxPdfParser(
            documents={
                document.sha256: (document.page_count, document.text)
                for document in fixture.documents
            },
            parser_version=fixture.parser_version,
        )
    if binding == "unconfigured":
        raise FileSafetyConfigurationError("file_parser_unconfigured")
    raise FileSafetyConfigurationError("file_parser_not_allowlisted")


def build_file_safety_pipeline(
    plan: RuntimeAdapterPlan,
    *,
    environ: Mapping[str, str] | None = None,
    clamd_transport: ClamdTransport | None = None,
) -> FileSafetyPipeline:
    return FileSafetyPipeline(
        scanner=build_malware_scanner(
            plan,
            environ=environ,
            clamd_transport=clamd_transport,
        ),
        parser=build_sandbox_pdf_parser(plan),
    )


def _validate_body(body: bytes) -> None:
    if not isinstance(body, bytes) or not body:
        raise FileSafetyError("file_body_invalid")
    if len(body) > MAX_BINARY_BYTES:
        raise FileSafetyError("file_body_too_large")


def _require_clean_scan(result: MalwareScanResult, expected_sha256: str) -> None:
    if not hmac.compare_digest(result.scanned_sha256, expected_sha256):
        raise FileSafetyError("malware_scan_digest_mismatch")
    if result.verdict is MalwareVerdict.INFECTED:
        raise FileSafetyError("malware_detected")


def _validate_parser_attestation(result: SandboxParseResult, expected_sha256: str) -> None:
    if not hmac.compare_digest(result.source_sha256, expected_sha256):
        raise FileSafetyError("sandbox_parser_source_mismatch")
    if (
        result.sandbox_profile != SANDBOX_PROFILE
        or result.network_disabled is not True
        or result.read_only_filesystem is not True
        or result.active_content_removed is not True
    ):
        raise FileSafetyError("sandbox_parser_attestation_invalid")


def _expand_candidates(
    reference: CorporateFilingReference,
    body: bytes,
) -> tuple[_ParseCandidate, ...]:
    declared_type = reference.media_type
    if declared_type == "application/pdf":
        _validate_pdf(body)
        return (_pdf_candidate(reference.document_id, reference.document_id, body),)
    if declared_type == "application/zip":
        if not _looks_like_zip(body):
            raise FileSafetyError("file_media_type_mismatch")
        return _expand_zip(reference.document_id, body)
    if declared_type == "application/octet-stream":
        if body.startswith(PDF_MAGIC):
            _validate_pdf(body)
            return (_pdf_candidate(reference.document_id, reference.document_id, body),)
        if _looks_like_zip(body):
            return _expand_zip(reference.document_id, body)
        raise FileSafetyError("file_type_unrecognised")
    raise FileSafetyError("file_type_not_allowlisted")


def _validate_pdf(body: bytes) -> None:
    _validate_body(body)
    if not body.startswith(PDF_MAGIC):
        raise FileSafetyError("file_media_type_mismatch")
    if any(signature in body[len(PDF_MAGIC) :] for signature in ZIP_MAGICS):
        raise FileSafetyError("file_polyglot_suspected")


def _looks_like_zip(body: bytes) -> bool:
    return any(body.startswith(signature) for signature in ZIP_MAGICS)


def _pdf_candidate(document_id: str, source_name: str, body: bytes) -> _ParseCandidate:
    return _ParseCandidate(
        document_id=document_id,
        source_name=source_name,
        body=body,
        sha256=hashlib.sha256(body).hexdigest(),
    )


def _expand_zip(document_id: str, body: bytes) -> tuple[_ParseCandidate, ...]:
    try:
        with ZipFile(BytesIO(body), mode="r", allowZip64=False) as archive:
            members = archive.infolist()
            if not members or len(members) > MAX_ARCHIVE_MEMBERS:
                raise FileSafetyError("archive_member_count_invalid")
            total_uncompressed = 0
            seen_names: set[str] = set()
            candidates: list[_ParseCandidate] = []
            for member in members:
                if member.is_dir():
                    continue
                source_name = _validate_archive_member(member, seen_names)
                total_uncompressed += member.file_size
                if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                    raise FileSafetyError("archive_uncompressed_limit_exceeded")
                member_body = _read_archive_member(archive, member)
                _validate_pdf(member_body)
                candidates.append(
                    _pdf_candidate(
                        f"{document_id}:{len(candidates) + 1}",
                        source_name,
                        member_body,
                    )
                )
            if not candidates:
                raise FileSafetyError("archive_contains_no_pdf")
            return tuple(candidates)
    except FileSafetyError:
        raise
    except (BadZipFile, LargeZipFile, NotImplementedError, RuntimeError, ValueError) as error:
        raise FileSafetyError("archive_invalid") from error


def _validate_archive_member(member: ZipInfo, seen_names: set[str]) -> str:
    filename = member.filename
    if not filename or len(filename) > MAX_ARCHIVE_MEMBER_NAME:
        raise FileSafetyError("archive_member_name_invalid")
    if "\x00" in filename or "\\" in filename or filename.startswith("/"):
        raise FileSafetyError("archive_member_path_unsafe")
    parts = filename.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise FileSafetyError("archive_member_path_unsafe")
    if ":" in parts[0]:
        raise FileSafetyError("archive_member_path_unsafe")
    normalised = "/".join(parts)
    collision_key = normalised.casefold()
    if collision_key in seen_names:
        raise FileSafetyError("archive_member_name_collision")
    seen_names.add(collision_key)

    mode = member.external_attr >> 16
    if stat.S_ISLNK(mode):
        raise FileSafetyError("archive_symlink_rejected")
    if member.flag_bits & 0x1:
        raise FileSafetyError("archive_encrypted_rejected")
    if member.compress_type not in ALLOWED_ZIP_COMPRESSION:
        raise FileSafetyError("archive_compression_not_allowlisted")
    if member.file_size <= 0 or member.file_size > MAX_ARCHIVE_MEMBER_BYTES:
        raise FileSafetyError("archive_member_size_invalid")
    ratio = member.file_size / max(member.compress_size, 1)
    if ratio > MAX_ARCHIVE_COMPRESSION_RATIO:
        raise FileSafetyError("archive_compression_ratio_exceeded")
    suffix = Path(parts[-1]).suffix.casefold()
    if suffix == ".zip":
        raise FileSafetyError("archive_nested_archive_rejected")
    if suffix != ".pdf":
        raise FileSafetyError("archive_member_type_not_allowlisted")
    return normalised


def _read_archive_member(archive: ZipFile, member: ZipInfo) -> bytes:
    chunks: list[bytes] = []
    total = 0
    with archive.open(member, mode="r") as stream:
        while True:
            chunk = stream.read(min(64 * 1024, MAX_ARCHIVE_MEMBER_BYTES - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_ARCHIVE_MEMBER_BYTES:
                raise FileSafetyError("archive_member_size_invalid")
    if total != member.file_size:
        raise FileSafetyError("archive_member_size_mismatch")
    return b"".join(chunks)
