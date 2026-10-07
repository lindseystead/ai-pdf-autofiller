"""Tests for hard-timeout PDF job execution."""

from __future__ import annotations

import os
import time

import pytest

from pdf_autofiller.api import jobs
from pdf_autofiller.pdf_reader import PdfPageLimitError


def _slow_job() -> None:
    time.sleep(5.0)


def _page_limit_job() -> None:
    raise PdfPageLimitError(num_pages=9, max_pages=2)


def _add_job(a: int, b: int) -> int:
    return a + b


def _crashing_job() -> None:
    os._exit(3)


def _large_result_job() -> str:
    # Larger than an OS pipe buffer (~64 KB): a parent that joins before
    # reading the queue deadlocks on results like this.
    return "x" * 500_000


def test_execute_pdf_job_thread_backend_returns_result(monkeypatch):
    monkeypatch.setenv("PDF_JOB_BACKEND", "thread")
    assert jobs.execute_pdf_job(_add_job, 2, 3, timeout_seconds=2.0) == 5


def test_execute_pdf_job_thread_backend_times_out(monkeypatch):
    monkeypatch.setenv("PDF_JOB_BACKEND", "thread")

    def slow() -> None:
        time.sleep(1.0)

    with pytest.raises(TimeoutError):
        jobs.execute_pdf_job(slow, timeout_seconds=0.05)


def test_execute_pdf_job_process_backend_times_out_and_kills(monkeypatch):
    monkeypatch.setenv("PDF_JOB_BACKEND", "process")

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        jobs.execute_pdf_job(_slow_job, timeout_seconds=0.2)
    elapsed = time.monotonic() - started
    assert elapsed < 2.0


def test_execute_pdf_job_process_reconstructs_page_limit(monkeypatch):
    monkeypatch.setenv("PDF_JOB_BACKEND", "process")

    with pytest.raises(PdfPageLimitError) as exc_info:
        # Spawn can be slow under full-suite load; keep budget generous.
        jobs.execute_pdf_job(_page_limit_job, timeout_seconds=30.0)
    assert exc_info.value.num_pages == 9
    assert exc_info.value.max_pages == 2


def test_execute_pdf_job_process_backend_returns_large_result(monkeypatch):
    monkeypatch.setenv("PDF_JOB_BACKEND", "process")

    started = time.monotonic()
    result = jobs.execute_pdf_job(_large_result_job, timeout_seconds=30.0)
    assert len(result) == 500_000
    assert time.monotonic() - started < 10.0


def test_execute_pdf_job_process_backend_reports_crash_without_waiting(monkeypatch):
    monkeypatch.setenv("PDF_JOB_BACKEND", "process")

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="exitcode=3"):
        jobs.execute_pdf_job(_crashing_job, timeout_seconds=30.0)
    assert time.monotonic() - started < 10.0


def _raise_invalid_pdf() -> None:
    from pdf_autofiller.pdf_reader import InvalidPdfError

    raise InvalidPdfError("PDF is password-protected; provide an unlocked copy")


def _raise_too_deep() -> None:
    from pdf_autofiller.user_data import UserDataTooDeepError

    raise UserDataTooDeepError(16)


def _raise_unresolved() -> None:
    from pdf_autofiller.pdf_writer import UnresolvedRequiredFieldsError

    raise UnresolvedRequiredFieldsError(missing_fields=["txtSSN"], skipped_fields=["txtDOB"])


def _raise_missing_file() -> None:
    raise FileNotFoundError("Input PDF not found: /nope.pdf")


def _raise_timeout() -> None:
    raise TimeoutError("provider took too long")


def _raise_unexpected() -> None:
    raise KeyError("boom")


def test_process_backend_rebuilds_each_library_error_with_its_details(monkeypatch):
    from pdf_autofiller import (
        InvalidPdfError,
        PdfAutofillerError,
        UnresolvedRequiredFieldsError,
        UserDataTooDeepError,
    )

    monkeypatch.setenv("PDF_JOB_BACKEND", "process")

    with pytest.raises(InvalidPdfError, match="password-protected") as invalid:
        jobs.execute_pdf_job(_raise_invalid_pdf, timeout_seconds=30.0)
    with pytest.raises(UserDataTooDeepError) as deep:
        jobs.execute_pdf_job(_raise_too_deep, timeout_seconds=30.0)
    with pytest.raises(UnresolvedRequiredFieldsError) as unresolved:
        jobs.execute_pdf_job(_raise_unresolved, timeout_seconds=30.0)

    assert deep.value.max_depth == 16
    assert (unresolved.value.missing_fields, unresolved.value.skipped_fields) == (["txtSSN"], ["txtDOB"])
    for error in (invalid.value, deep.value, unresolved.value):
        assert isinstance(error, PdfAutofillerError)


def test_process_backend_rebuilds_builtin_errors_and_wraps_unexpected_ones(monkeypatch):
    monkeypatch.setenv("PDF_JOB_BACKEND", "process")
    with pytest.raises(FileNotFoundError, match=r"/nope\.pdf"):
        jobs.execute_pdf_job(_raise_missing_file, timeout_seconds=30.0)
    with pytest.raises(TimeoutError, match="provider took too long"):
        jobs.execute_pdf_job(_raise_timeout, timeout_seconds=30.0)
    with pytest.raises(RuntimeError, match="KeyError"):
        jobs.execute_pdf_job(_raise_unexpected, timeout_seconds=30.0)
