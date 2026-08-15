"""
Hostile and malformed documents must fail with a typed error, never a 500.

Every case here previously either crashed, hung, or — worse — succeeded quietly
with zero fields, which sent the user looking for a mapping bug that did not
exist. The assertion in each test is the same: the caller gets a named,
actionable error.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject, TextStringObject

from pdf_autofiller.errors import (
    EncryptedPdfError,
    PdfParseError,
    PdfProcessingTimeoutError,
    XfaFormError,
)
from pdf_autofiller.execution import run_isolated
from pdf_autofiller.pdf_reader import read_pdf

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "sample_form.pdf"


def _write(tmp_path: Path, name: str, build) -> Path:
    target = tmp_path / name
    writer = PdfWriter()
    build(writer)
    with target.open("wb") as handle:
        writer.write(handle)
    return target


def test_encrypted_pdf_raises_named_error(tmp_path):
    def build(writer: PdfWriter) -> None:
        writer.append(PdfReader(str(SAMPLE)))
        writer.encrypt("a-password")

    path = _write(tmp_path, "encrypted.pdf", build)
    with pytest.raises(EncryptedPdfError) as excinfo:
        read_pdf(path)
    assert excinfo.value.code == "pdf_encrypted"
    assert excinfo.value.status_code == 422
    assert "password" in str(excinfo.value).lower()


def test_xfa_pdf_raises_named_error(tmp_path):
    """XFA forms read as zero AcroForm fields, so they must be rejected up front."""

    def build(writer: PdfWriter) -> None:
        writer.clone_reader_document_root(PdfReader(str(SAMPLE)))
        acroform = writer.root_object[NameObject("/AcroForm")]
        acroform[NameObject("/XFA")] = ArrayObject([TextStringObject("<xdp:xdp/>")])

    path = _write(tmp_path, "xfa.pdf", build)
    with pytest.raises(XfaFormError) as excinfo:
        read_pdf(path)
    assert excinfo.value.code == "pdf_xfa_unsupported"
    assert excinfo.value.details()["has_acroform_fallback"] is True


def test_truncated_pdf_raises_parse_error(tmp_path):
    path = tmp_path / "truncated.pdf"
    path.write_bytes(SAMPLE.read_bytes()[:400])
    with pytest.raises(PdfParseError):
        read_pdf(path)


def test_garbage_with_pdf_header_raises_parse_error(tmp_path):
    path = tmp_path / "garbage.pdf"
    path.write_bytes(b"%PDF-1.7\n" + b"\x00\xff" * 500)
    with pytest.raises(PdfParseError):
        read_pdf(path)


def test_empty_file_raises_parse_error(tmp_path):
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")
    with pytest.raises(PdfParseError):
        read_pdf(path)


def test_missing_file_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_pdf(tmp_path / "nope.pdf")


def test_page_limit_rejects_before_extraction(tmp_path):
    from pdf_autofiller.errors import PdfPageLimitError

    def build(writer: PdfWriter) -> None:
        for _ in range(5):
            writer.add_blank_page(width=200, height=200)

    path = _write(tmp_path, "many.pdf", build)
    with pytest.raises(PdfPageLimitError) as excinfo:
        read_pdf(path, max_pages=2)
    assert excinfo.value.details() == {"num_pages": 5, "max_pages": 2}


# --- process isolation -----------------------------------------------------


def _sleep_forever(seconds: float) -> str:
    """Stand-in for a PDF that pins a worker; must be module-level to pickle."""
    time.sleep(seconds)
    return "never returned"


def _raise_domain_error() -> None:
    raise XfaFormError(has_acroform_fallback=False)


def test_runaway_work_is_killed_not_merely_abandoned():
    """A timeout must stop the work, not just stop waiting for it.

    asyncio.wait_for around a thread returns control while the thread keeps
    running; enough hostile documents then exhaust the pool while the service
    still reports healthy.
    """
    started = time.monotonic()
    with pytest.raises(PdfProcessingTimeoutError):
        run_isolated(_sleep_forever, 30.0, timeout=0.5)
    elapsed = time.monotonic() - started
    assert elapsed < 10.0, "timeout did not actually interrupt the worker"


def test_domain_errors_survive_the_process_boundary():
    """Typed errors must keep their code and details when raised in a child."""
    with pytest.raises(Exception) as excinfo:
        run_isolated(_raise_domain_error, timeout=10)
    assert excinfo.value.code == "pdf_xfa_unsupported"
    assert excinfo.value.status_code == 422
    assert excinfo.value.details() == {"has_acroform_fallback": False}


def test_isolation_can_be_disabled_for_in_process_use():
    assert run_isolated(_sleep_forever, 0.0, timeout=5, enabled=False) == "never returned"
