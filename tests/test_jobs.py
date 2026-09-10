"""Tests for hard-timeout PDF job execution."""

from __future__ import annotations

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
