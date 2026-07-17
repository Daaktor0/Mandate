from __future__ import annotations

import asyncio
import hashlib
import json
import stat
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo

import pytest
from mandate_worker.fixtures import AdapterCapability, FixtureCatalog
from mandate_worker.providers import file_safety as file_safety_module
from mandate_worker.providers.corporate_filings import (
    CorporateFilingAcquisitionMethod,
    CorporateFilingReference,
    CorporateFilingType,
    register_untrusted_corporate_filing,
)
from mandate_worker.providers.file_safety import (
    ClamdMalwareScanner,
    FileSafetyConfigurationError,
    FileSafetyError,
    FileSafetyPipeline,
    FixtureMalwareScanner,
    FixtureSandboxPdfParser,
    MalwareScanResult,
    MalwareVerdict,
    QuarantinedBinary,
    SafeParsedDocument,
    SandboxParseResult,
    UnixClamdTransport,
    build_file_safety_pipeline,
    build_malware_scanner,
    build_sandbox_pdf_parser,
)
from mandate_worker.runtime import RuntimeAdapterPlan, build_runtime_adapter_plan
from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPOSITORY_ROOT / "fixtures" / "demo"
PRIVATE_CIN = "U62099MH2024PTC123456"
PDF_ONE = b"%PDF-1.4\nSynthetic AOC-4 filing fixture for Mandate demo mode.\n%%EOF"
PDF_TWO = b"%PDF-1.4\nSynthetic MGT-7 filing fixture for Mandate demo mode.\n%%EOF"
ZIP_EPOCH = (2026, 1, 1, 0, 0, 0)


def sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def make_reference(
    body: bytes,
    *,
    media_type: str = "application/pdf",
    document_id: str = "test:filing:1",
) -> CorporateFilingReference:
    assert media_type in {"application/pdf", "application/zip", "application/octet-stream"}
    return register_untrusted_corporate_filing(
        document_id=document_id,
        cin=PRIVATE_CIN,
        filing_type=CorporateFilingType.AOC_4,
        financial_year="2024-25",
        acquisition_method=CorporateFilingAcquisitionMethod.FIXTURE,
        source_provider="fixture",
        source_locator="fixture/test/filing",
        media_type=media_type,  # type: ignore[arg-type]
        body=body,
        acquired_at=datetime(2026, 7, 15, tzinfo=UTC),
    )


def make_zip(*members: tuple[ZipInfo, bytes]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, mode="w") as archive:
        for info, body in members:
            archive.writestr(info, body)
    return buffer.getvalue()


def member(name: str, *, compress_type: int = ZIP_STORED, **attributes: int) -> ZipInfo:
    info = ZipInfo(name, date_time=ZIP_EPOCH)
    # Python normalises backslashes in ZipInfo.__init__; restore the raw member
    # name so the traversal case exercises the archive boundary itself.
    info.filename = name
    info.compress_type = compress_type
    for key, value in attributes.items():
        setattr(info, key, value)
    return info


def scanner_for(
    *clean_bodies: bytes, infected: dict[str, str] | None = None
) -> FixtureMalwareScanner:
    return FixtureMalwareScanner(
        clean_sha256s=frozenset(sha256(body) for body in clean_bodies),
        infected_sha256s=infected or {},
        engine_version="fixture-clamav-test",
        signature_version="2026-07-17.test",
    )


def parser_for(*bodies: bytes) -> FixtureSandboxPdfParser:
    return FixtureSandboxPdfParser(
        documents={sha256(body): (1, f"Parsed text for {sha256(body)[:8]}") for body in bodies},
        parser_version="fixture-pdf-parser-test",
    )


def pipeline_for(
    *clean_bodies: bytes,
    infected: dict[str, str] | None = None,
) -> FileSafetyPipeline:
    return FileSafetyPipeline(
        scanner=scanner_for(*clean_bodies, infected=infected),
        parser=parser_for(*clean_bodies),
    )


def live_plan(bindings: dict[AdapterCapability, str]) -> RuntimeAdapterPlan:
    return RuntimeAdapterPlan(demo_mode=False, bindings=MappingProxyType(bindings))


@dataclass(frozen=True, slots=True)
class StubClamdTransport:
    reply: str

    async def scan_stream(self, body: bytes) -> str:
        return self.reply


# --- Quarantine integrity -----------------------------------------------------------


def test_SEC_05_quarantined_binary_rejects_digest_mismatch() -> None:
    reference = make_reference(PDF_ONE)
    tampered = PDF_ONE[:-1] + b"?"

    with pytest.raises(FileSafetyError, match="file_digest_mismatch"):
        QuarantinedBinary(reference=reference, body=tampered)


def test_SEC_05_quarantined_binary_rejects_size_mismatch() -> None:
    reference = make_reference(PDF_ONE)

    with pytest.raises(FileSafetyError, match="file_size_mismatch"):
        QuarantinedBinary(reference=reference, body=PDF_ONE + b"x")


def test_SEC_05_quarantined_binary_rejects_empty_and_oversized_bodies() -> None:
    reference = make_reference(PDF_ONE)

    with pytest.raises(FileSafetyError, match="file_body_invalid"):
        QuarantinedBinary(reference=reference, body=b"")

    oversized = b"%PDF-" + b"0" * file_safety_module.MAX_BINARY_BYTES
    with pytest.raises(FileSafetyError, match="file_body_too_large"):
        QuarantinedBinary(reference=reference, body=oversized)


@pytest.mark.asyncio
async def test_SEC_05_pipeline_rejects_swapped_bytes_before_scanning() -> None:
    reference = make_reference(PDF_ONE)

    with pytest.raises(FileSafetyError, match="file_digest_mismatch"):
        await pipeline_for(PDF_ONE, PDF_TWO).process(reference, PDF_TWO[: len(PDF_ONE)])


# --- Malware scanning ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_SEC_05_infected_fixture_verdict_blocks_parsing() -> None:
    reference = make_reference(PDF_ONE)
    pipeline = FileSafetyPipeline(
        scanner=scanner_for(infected={sha256(PDF_ONE): "Eicar-Test-Signature"}),
        parser=parser_for(PDF_ONE),
    )

    with pytest.raises(FileSafetyError, match="malware_detected"):
        await pipeline.process(reference, PDF_ONE)


@pytest.mark.asyncio
async def test_SEC_05_unknown_binary_fails_closed_in_demo_mode() -> None:
    unknown = b"%PDF-1.4\nnot registered in any fixture\n%%EOF"

    with pytest.raises(FileSafetyError, match="malware_fixture_missing"):
        await scanner_for(PDF_ONE).scan(unknown)


@pytest.mark.asyncio
async def test_SEC_05_scan_digest_mismatch_is_rejected_by_pipeline() -> None:
    class WrongDigestScanner:
        async def scan(self, body: bytes) -> MalwareScanResult:
            return MalwareScanResult(
                provider="fixture",
                verdict=MalwareVerdict.CLEAN,
                scanned_sha256="0" * 64,
            )

    reference = make_reference(PDF_ONE)
    pipeline = FileSafetyPipeline(scanner=WrongDigestScanner(), parser=parser_for(PDF_ONE))

    with pytest.raises(FileSafetyError, match="malware_scan_digest_mismatch"):
        await pipeline.process(reference, PDF_ONE)


def test_SEC_05_malware_result_shape_is_strict() -> None:
    with pytest.raises(ValidationError):
        MalwareScanResult(
            provider="fixture",
            verdict=MalwareVerdict.CLEAN,
            scanned_sha256=sha256(PDF_ONE),
            threat_name="must-not-appear-on-clean",
        )
    with pytest.raises(ValidationError):
        MalwareScanResult(
            provider="fixture",
            verdict=MalwareVerdict.INFECTED,
            scanned_sha256=sha256(PDF_ONE),
        )


@pytest.mark.asyncio
async def test_SEC_05_clamd_replies_map_to_verdicts_without_raw_output() -> None:
    clean = await ClamdMalwareScanner(StubClamdTransport("stream: OK")).scan(PDF_ONE)
    assert clean.verdict is MalwareVerdict.CLEAN
    assert clean.scanned_sha256 == sha256(PDF_ONE)

    infected = await ClamdMalwareScanner(
        StubClamdTransport("stream: Win.Test.EICAR_HDB-1 FOUND")
    ).scan(PDF_ONE)
    assert infected.verdict is MalwareVerdict.INFECTED
    assert infected.threat_name == "Win.Test.EICAR_HDB-1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reply", "code"),
    [
        ("INSTREAM size limit exceeded. ERROR", "malware_scanner_error"),
        ("stream:  FOUND", "malware_scanner_reply_invalid"),
        ("unparseable gibberish", "malware_scanner_reply_invalid"),
    ],
)
async def test_SEC_05_clamd_error_and_malformed_replies_fail_closed(reply: str, code: str) -> None:
    with pytest.raises(FileSafetyError, match=code):
        await ClamdMalwareScanner(StubClamdTransport(reply)).scan(PDF_ONE)


@pytest.mark.asyncio
async def test_SEC_05_unavailable_clamd_socket_is_a_retryable_failure(tmp_path: Path) -> None:
    transport = UnixClamdTransport(tmp_path / "missing" / "clamd.sock", timeout_seconds=1.0)

    with pytest.raises(FileSafetyError, match="malware_scanner_unavailable") as failure:
        await transport.scan_stream(PDF_ONE)
    assert failure.value.retryable is True


@pytest.mark.asyncio
async def test_SEC_05_clamd_transport_speaks_instream_framing(tmp_path: Path) -> None:
    socket_path = tmp_path / "clamd.sock"
    received: list[bytes] = []

    async def fake_clamd(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        command = await reader.readuntil(b"\0")
        received.append(command)
        chunks: list[bytes] = []
        while True:
            size = struct.unpack(">I", await reader.readexactly(4))[0]
            if size == 0:
                break
            chunks.append(await reader.readexactly(size))
        received.append(b"".join(chunks))
        writer.write(b"stream: OK\0")
        await writer.drain()
        writer.close()

    server = await asyncio.start_unix_server(fake_clamd, path=str(socket_path))
    try:
        transport = UnixClamdTransport(socket_path, chunk_size=16)
        result = await ClamdMalwareScanner(transport).scan(PDF_ONE)
    finally:
        server.close()
        await server.wait_closed()

    assert result.verdict is MalwareVerdict.CLEAN
    assert received == [b"zINSTREAM\0", PDF_ONE]


def test_SEC_05_clamd_transport_configuration_is_bounded(tmp_path: Path) -> None:
    with pytest.raises(FileSafetyConfigurationError, match="clamd_socket_must_be_absolute"):
        UnixClamdTransport(Path("relative/clamd.sock"))
    with pytest.raises(FileSafetyConfigurationError, match="clamd_timeout_invalid"):
        UnixClamdTransport(tmp_path / "clamd.sock", timeout_seconds=0)
    with pytest.raises(FileSafetyConfigurationError, match="clamd_chunk_size_invalid"):
        UnixClamdTransport(tmp_path / "clamd.sock", chunk_size=0)


# --- Media-type, magic and polyglot checks ------------------------------------------


@pytest.mark.asyncio
async def test_SEC_05_pdf_media_type_with_zip_bytes_is_rejected() -> None:
    body = make_zip((member("doc.pdf"), PDF_ONE))
    reference = make_reference(body, media_type="application/pdf")

    with pytest.raises(FileSafetyError, match="file_media_type_mismatch"):
        await pipeline_for(body).process(reference, body)


@pytest.mark.asyncio
async def test_SEC_05_zip_media_type_with_pdf_bytes_is_rejected() -> None:
    reference = make_reference(PDF_ONE, media_type="application/zip")

    with pytest.raises(FileSafetyError, match="file_media_type_mismatch"):
        await pipeline_for(PDF_ONE).process(reference, PDF_ONE)


@pytest.mark.asyncio
async def test_SEC_05_pdf_zip_polyglot_is_rejected() -> None:
    polyglot = b"%PDF-1.4\n" + make_zip((member("hidden.pdf"), PDF_ONE)) + b"\n%%EOF"
    reference = make_reference(polyglot, media_type="application/pdf")

    with pytest.raises(FileSafetyError, match="file_polyglot_suspected"):
        await pipeline_for(polyglot).process(reference, polyglot)


@pytest.mark.asyncio
async def test_SEC_05_unrecognised_octet_stream_is_rejected() -> None:
    body = b"MZ this is neither a PDF nor a ZIP"
    reference = make_reference(body, media_type="application/octet-stream")

    with pytest.raises(FileSafetyError, match="file_type_unrecognised"):
        await pipeline_for(body).process(reference, body)


@pytest.mark.asyncio
async def test_SEC_05_corrupt_zip_bytes_are_rejected() -> None:
    body = b"PK\x03\x04 corrupt central directory"
    reference = make_reference(body, media_type="application/zip")

    with pytest.raises(FileSafetyError, match="archive_invalid"):
        await pipeline_for(body).process(reference, body)


# --- Archive member validation ------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "name",
    [
        "../escape.pdf",
        "/absolute.pdf",
        "nested/../../escape.pdf",
        "windows\\style.pdf",
        "C:drive.pdf",
        "trailing/./dot.pdf",
    ],
)
async def test_SEC_05_traversal_and_unsafe_member_paths_are_rejected(name: str) -> None:
    body = make_zip((member(name), PDF_ONE))
    reference = make_reference(body, media_type="application/zip")

    with pytest.raises(FileSafetyError, match="archive_member_path_unsafe"):
        await pipeline_for(body, PDF_ONE).process(reference, body)


@pytest.mark.asyncio
async def test_SEC_05_duplicate_case_folded_member_names_are_rejected() -> None:
    body = make_zip((member("Filing.pdf"), PDF_ONE), (member("filing.PDF"), PDF_TWO))
    reference = make_reference(body, media_type="application/zip")

    with pytest.raises(FileSafetyError, match="archive_member_name_collision"):
        await pipeline_for(body, PDF_ONE, PDF_TWO).process(reference, body)


@pytest.mark.asyncio
async def test_SEC_05_overlong_member_name_is_rejected() -> None:
    name = "a" * (file_safety_module.MAX_ARCHIVE_MEMBER_NAME + 1 - len(".pdf")) + ".pdf"
    body = make_zip((member(name), PDF_ONE))
    reference = make_reference(body, media_type="application/zip")

    with pytest.raises(FileSafetyError, match="archive_member_name_invalid"):
        await pipeline_for(body, PDF_ONE).process(reference, body)


@pytest.mark.asyncio
async def test_SEC_05_symlink_members_are_rejected() -> None:
    body = make_zip(
        (member("link.pdf", external_attr=(stat.S_IFLNK | 0o777) << 16), b"/etc/passwd")
    )
    reference = make_reference(body, media_type="application/zip")

    with pytest.raises(FileSafetyError, match="archive_symlink_rejected"):
        await pipeline_for(body).process(reference, body)


@pytest.mark.asyncio
async def test_SEC_05_encrypted_members_are_rejected() -> None:
    raw = bytearray(make_zip((member("secret.pdf"), PDF_ONE)))
    central_directory = raw.find(b"PK\x01\x02")
    assert central_directory >= 0
    raw[central_directory + 8] |= 0x1
    body = bytes(raw)
    reference = make_reference(body, media_type="application/zip")

    with pytest.raises(FileSafetyError, match="archive_encrypted_rejected"):
        await pipeline_for(body, PDF_ONE).process(reference, body)


@pytest.mark.asyncio
async def test_SEC_05_nested_archives_are_rejected() -> None:
    inner = make_zip((member("deep.pdf"), PDF_ONE))
    body = make_zip((member("inner.zip"), inner))
    reference = make_reference(body, media_type="application/zip")

    with pytest.raises(FileSafetyError, match="archive_nested_archive_rejected"):
        await pipeline_for(body).process(reference, body)


@pytest.mark.asyncio
async def test_SEC_05_non_pdf_members_are_rejected() -> None:
    body = make_zip((member("notes.txt"), b"plain text"))
    reference = make_reference(body, media_type="application/zip")

    with pytest.raises(FileSafetyError, match="archive_member_type_not_allowlisted"):
        await pipeline_for(body).process(reference, body)


@pytest.mark.asyncio
async def test_SEC_05_member_count_limit_is_enforced() -> None:
    members = tuple(
        (member(f"filing-{index}.pdf"), PDF_ONE)
        for index in range(file_safety_module.MAX_ARCHIVE_MEMBERS + 1)
    )
    body = make_zip(*members)
    reference = make_reference(body, media_type="application/zip")

    with pytest.raises(FileSafetyError, match="archive_member_count_invalid"):
        await pipeline_for(body, PDF_ONE).process(reference, body)


@pytest.mark.asyncio
async def test_SEC_05_empty_archive_and_directory_only_archive_are_rejected() -> None:
    empty = make_zip()
    reference = make_reference(empty, media_type="application/zip")
    with pytest.raises(FileSafetyError, match="archive_member_count_invalid"):
        await pipeline_for(empty).process(reference, empty)

    directories = make_zip((member("only-a-directory/"), b""))
    reference = make_reference(directories, media_type="application/zip")
    with pytest.raises(FileSafetyError, match="archive_contains_no_pdf"):
        await pipeline_for(directories).process(reference, directories)


@pytest.mark.asyncio
async def test_SEC_05_zero_byte_member_is_rejected() -> None:
    body = make_zip((member("empty.pdf"), b""))
    reference = make_reference(body, media_type="application/zip")

    with pytest.raises(FileSafetyError, match="archive_member_size_invalid"):
        await pipeline_for(body).process(reference, body)


@pytest.mark.asyncio
async def test_SEC_05_member_size_limit_is_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_safety_module, "MAX_ARCHIVE_MEMBER_BYTES", 16)
    body = make_zip((member("big.pdf"), PDF_ONE))
    reference = make_reference(body, media_type="application/zip")

    with pytest.raises(FileSafetyError, match="archive_member_size_invalid"):
        await pipeline_for(body, PDF_ONE).process(reference, body)


@pytest.mark.asyncio
async def test_SEC_05_total_uncompressed_limit_is_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        file_safety_module, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", len(PDF_ONE) + len(PDF_TWO) - 1
    )
    body = make_zip((member("one.pdf"), PDF_ONE), (member("two.pdf"), PDF_TWO))
    reference = make_reference(body, media_type="application/zip")

    with pytest.raises(FileSafetyError, match="archive_uncompressed_limit_exceeded"):
        await pipeline_for(body, PDF_ONE, PDF_TWO).process(reference, body)


@pytest.mark.asyncio
async def test_SEC_05_decompression_bomb_ratio_is_rejected() -> None:
    bomb = b"%PDF-" + b"0" * (2 * 1024 * 1024)
    body = make_zip((member("bomb.pdf", compress_type=ZIP_DEFLATED), bomb))
    reference = make_reference(body, media_type="application/zip")

    with pytest.raises(FileSafetyError, match="archive_compression_ratio_exceeded"):
        await pipeline_for(body).process(reference, body)


@pytest.mark.asyncio
async def test_SEC_05_infected_archive_member_blocks_the_whole_archive() -> None:
    body = make_zip((member("clean.pdf"), PDF_ONE), (member("infected.pdf"), PDF_TWO))
    reference = make_reference(body, media_type="application/zip")
    pipeline = FileSafetyPipeline(
        scanner=scanner_for(body, PDF_ONE, infected={sha256(PDF_TWO): "Eicar-Test-Signature"}),
        parser=parser_for(PDF_ONE, PDF_TWO),
    )

    with pytest.raises(FileSafetyError, match="malware_detected"):
        await pipeline.process(reference, body)


# --- Sandbox parser attestation -----------------------------------------------------


@pytest.mark.asyncio
async def test_SEC_05_parser_source_digest_mismatch_is_rejected() -> None:
    parser = parser_for(PDF_ONE)

    with pytest.raises(FileSafetyError, match="sandbox_parser_source_mismatch"):
        await parser.parse_pdf(PDF_ONE, source_sha256=sha256(PDF_TWO))


@pytest.mark.asyncio
async def test_SEC_05_pipeline_rejects_parser_result_for_a_different_document() -> None:
    class MisattributedParser:
        async def parse_pdf(self, body: bytes, *, source_sha256: str) -> SandboxParseResult:
            text = "Text attributed to the wrong source document."
            return SandboxParseResult(
                source_sha256=sha256(PDF_TWO),
                parser="stub",
                parser_version="stub-1",
                page_count=1,
                text=text,
                text_sha256=sha256(text.encode("utf-8")),
            )

    reference = make_reference(PDF_ONE)
    pipeline = FileSafetyPipeline(scanner=scanner_for(PDF_ONE), parser=MisattributedParser())

    with pytest.raises(FileSafetyError, match="sandbox_parser_source_mismatch"):
        await pipeline.process(reference, PDF_ONE)


def test_SEC_05_sandbox_attestation_cannot_be_weakened() -> None:
    text = "Attested text."
    valid = {
        "source_sha256": sha256(PDF_ONE),
        "parser": "fixture",
        "parser_version": "fixture-pdf-parser-test",
        "page_count": 1,
        "text": text,
        "text_sha256": sha256(text.encode("utf-8")),
    }

    assert SandboxParseResult.model_validate(valid).network_disabled is True
    for weakened in (
        {"network_disabled": False},
        {"read_only_filesystem": False},
        {"active_content_removed": False},
        {"sandbox_profile": "permissive_v0"},
    ):
        with pytest.raises(ValidationError):
            SandboxParseResult.model_validate({**valid, **weakened})

    with pytest.raises(ValidationError, match="digest mismatch"):
        SandboxParseResult.model_validate({**valid, "text_sha256": "0" * 64})


@pytest.mark.asyncio
async def test_SEC_05_parser_fixture_missing_document_fails_closed() -> None:
    parser = parser_for(PDF_TWO)

    with pytest.raises(FileSafetyError, match="sandbox_parser_fixture_missing"):
        await parser.parse_pdf(PDF_ONE, source_sha256=sha256(PDF_ONE))


# --- Successful demo parsing and non-admission --------------------------------------


@pytest.mark.asyncio
async def test_RUN_06_demo_catalog_pdf_passes_the_full_gate_without_admission() -> None:
    plan = build_runtime_adapter_plan({"DEMO_MODE": "1"}, fixture_root=FIXTURE_ROOT)
    pipeline = build_file_safety_pipeline(plan)
    filings = json.loads((FIXTURE_ROOT / "corporate_filings" / "smoke.json").read_text())
    document = filings["documents"][0]
    body = document["bodyUtf8"].encode("utf-8")
    reference = make_reference(body, document_id="fixture:aoc-4:2024-25")

    result = await pipeline.process(reference, body)

    assert result.source_sha256 == sha256(body)
    assert [scan.verdict for scan in result.malware_scans] == [MalwareVerdict.CLEAN]
    assert len(result.documents) == 1
    parsed = result.documents[0]
    assert parsed.text == "Synthetic AOC-4 filing text for Mandate demo mode."
    assert parsed.untrusted is True
    assert parsed.evidence_admitted is False
    assert result.evidence_admitted is False


@pytest.mark.asyncio
async def test_RUN_06_zip_of_scanned_pdfs_passes_with_per_member_scans() -> None:
    body = make_zip((member("aoc-4.pdf"), PDF_ONE), (member("year/mgt-7.pdf"), PDF_TWO))
    reference = make_reference(body, media_type="application/zip", document_id="test:zip:1")
    pipeline = pipeline_for(body, PDF_ONE, PDF_TWO)

    result = await pipeline.process(reference, body)

    assert {scan.scanned_sha256 for scan in result.malware_scans} == {
        sha256(body),
        sha256(PDF_ONE),
        sha256(PDF_TWO),
    }
    assert [document.source_name for document in result.documents] == [
        "aoc-4.pdf",
        "year/mgt-7.pdf",
    ]
    assert [document.document_id for document in result.documents] == [
        "test:zip:1:1",
        "test:zip:1:2",
    ]
    assert all(document.evidence_admitted is False for document in result.documents)
    assert all(document.untrusted is True for document in result.documents)


def test_RUN_06_parsed_documents_cannot_claim_admission() -> None:
    text = "Parsed but never admitted."
    valid = {
        "document_id": "test:filing:1",
        "source_name": "filing.pdf",
        "source_sha256": sha256(PDF_ONE),
        "parser": "fixture",
        "parser_version": "fixture-pdf-parser-test",
        "page_count": 1,
        "text": text,
        "text_sha256": sha256(text.encode("utf-8")),
    }

    assert SafeParsedDocument.model_validate(valid).evidence_admitted is False
    for forbidden in (
        {"evidence_admitted": True},
        {"untrusted": False},
        {"parse_allowed": False},
    ):
        with pytest.raises(ValidationError):
            SafeParsedDocument.model_validate({**valid, **forbidden})


# --- Fail-closed provider selection -------------------------------------------------


def test_NFR_03_demo_plan_builds_fixture_scanner_and_parser() -> None:
    plan = build_runtime_adapter_plan({"DEMO_MODE": "1"}, fixture_root=FIXTURE_ROOT)

    assert isinstance(build_malware_scanner(plan), FixtureMalwareScanner)
    assert isinstance(build_sandbox_pdf_parser(plan), FixtureSandboxPdfParser)


def test_NFR_03_fixture_bindings_require_demo_mode() -> None:
    plan = live_plan(
        {
            AdapterCapability.MALWARE_SCANNER: "fixture",
            AdapterCapability.FILE_PARSER: "fixture",
        }
    )

    with pytest.raises(FileSafetyConfigurationError, match="malware_fixture_requires_demo_mode"):
        build_malware_scanner(plan)
    with pytest.raises(
        FileSafetyConfigurationError, match="file_parser_fixture_requires_demo_mode"
    ):
        build_sandbox_pdf_parser(plan)


def test_NFR_03_unconfigured_and_unknown_bindings_fail_closed() -> None:
    unconfigured = live_plan(
        {
            AdapterCapability.MALWARE_SCANNER: "unconfigured",
            AdapterCapability.FILE_PARSER: "unconfigured",
        }
    )
    with pytest.raises(FileSafetyConfigurationError, match="malware_scanner_unconfigured"):
        build_malware_scanner(unconfigured)
    with pytest.raises(FileSafetyConfigurationError, match="file_parser_unconfigured"):
        build_sandbox_pdf_parser(unconfigured)

    unknown = live_plan(
        {
            AdapterCapability.MALWARE_SCANNER: "virustotal",
            AdapterCapability.FILE_PARSER: "pdfminer_local",
        }
    )
    with pytest.raises(FileSafetyConfigurationError, match="malware_scanner_not_allowlisted"):
        build_malware_scanner(unknown)
    with pytest.raises(FileSafetyConfigurationError, match="file_parser_not_allowlisted"):
        build_sandbox_pdf_parser(unknown)


def test_NFR_03_live_parsing_stays_disabled_even_with_clamd_available(tmp_path: Path) -> None:
    plan = live_plan(
        {
            AdapterCapability.MALWARE_SCANNER: "clamd_unix",
            AdapterCapability.FILE_PARSER: "sandboxed_service",
        }
    )
    environ = {"CLAMD_SOCKET_PATH": str(tmp_path / "clamd.sock")}

    assert isinstance(build_malware_scanner(plan, environ=environ), ClamdMalwareScanner)
    with pytest.raises(FileSafetyConfigurationError, match="file_parser_not_allowlisted"):
        build_file_safety_pipeline(plan, environ=environ)


def test_NFR_03_clamd_binding_requires_a_socket_path() -> None:
    plan = live_plan({AdapterCapability.MALWARE_SCANNER: "clamd_unix"})

    with pytest.raises(FileSafetyConfigurationError, match="clamd_socket_missing"):
        build_malware_scanner(plan, environ={})


def test_NFR_03_malware_fixture_payload_is_validated(tmp_path: Path) -> None:
    plan = build_runtime_adapter_plan({"DEMO_MODE": "1"}, fixture_root=FIXTURE_ROOT)
    catalog = plan.catalog
    assert isinstance(catalog, FixtureCatalog)

    class BrokenCatalog:
        manifest = catalog.manifest

        def payload(self, capability: AdapterCapability) -> dict[str, object]:
            return {"fixtureVersion": 1, "cleanSha256s": ["not-a-digest"]}

    broken = RuntimeAdapterPlan(
        demo_mode=True,
        bindings=plan.bindings,
        catalog=BrokenCatalog(),  # type: ignore[arg-type]
    )
    with pytest.raises(FileSafetyConfigurationError, match="malware_fixture_invalid"):
        build_malware_scanner(broken)
    with pytest.raises(FileSafetyConfigurationError, match="file_parser_fixture_invalid"):
        build_sandbox_pdf_parser(broken)
