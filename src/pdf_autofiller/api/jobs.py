"""Bounded PDF job execution with hard timeout isolation.

``asyncio.wait_for`` around ``to_thread`` cannot stop CPU-bound pypdf work.
This module runs pipeline jobs in a child process so timeouts can terminate
the worker and reclaim CPU/memory.
"""

from __future__ import annotations

import logging
import multiprocessing as mp
import os
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from multiprocessing.connection import Connection, wait
from multiprocessing.process import BaseProcess
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

PDF_MAX_CONCURRENT = max(1, int(os.getenv("PDF_MAX_CONCURRENT", "2")))

_thread_pool: ThreadPoolExecutor | None = None
# Parent-process only: limit concurrent PDF jobs (works for both backends).
_job_slots = threading.BoundedSemaphore(PDF_MAX_CONCURRENT)


def _get_thread_pool() -> ThreadPoolExecutor:
    global _thread_pool
    if _thread_pool is None:
        _thread_pool = ThreadPoolExecutor(
            max_workers=PDF_MAX_CONCURRENT,
            thread_name_prefix="pdf-job",
        )
    return _thread_pool


def _process_target(
    func: Callable[..., T],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    conn: Connection,
) -> None:
    """Child-process entry: send (ok, result) or (err, payload) to the parent."""
    try:
        conn.send(("ok", func(*args, **kwargs)))
    except Exception as exc:
        conn.send(
            (
                "err",
                {
                    "type": type(exc).__name__,
                    "message": str(exc),
                    "traceback": traceback.format_exc(),
                    "attrs": {
                        key: getattr(exc, key)
                        for key in (
                            "missing_fields",
                            "skipped_fields",
                            "num_pages",
                            "max_pages",
                            "max_depth",
                        )
                        if hasattr(exc, key)
                    },
                },
            )
        )


def _raise_serialized_error(payload: dict[str, Any]) -> None:
    """Re-raise known pipeline errors reconstructed from the child process."""
    from pdf_autofiller.pdf_reader import InvalidPdfError, PdfPageLimitError
    from pdf_autofiller.pdf_writer import UnresolvedRequiredFieldsError

    err_type = payload.get("type", "RuntimeError")
    message = payload.get("message", "PDF job failed")
    attrs = payload.get("attrs") or {}

    if err_type == "UnresolvedRequiredFieldsError":
        raise UnresolvedRequiredFieldsError(
            missing_fields=list(attrs.get("missing_fields") or []),
            skipped_fields=list(attrs.get("skipped_fields") or []),
        )
    if err_type == "PdfPageLimitError":
        raise PdfPageLimitError(
            num_pages=int(attrs.get("num_pages") or 0),
            max_pages=int(attrs.get("max_pages") or 0),
        )
    if err_type == "InvalidPdfError":
        raise InvalidPdfError(message)
    if err_type == "UserDataTooDeepError":
        from pdf_autofiller.user_data import UserDataTooDeepError

        raise UserDataTooDeepError(int(attrs.get("max_depth") or 0))
    if err_type == "FileNotFoundError":
        raise FileNotFoundError(message)
    if err_type == "TimeoutError":
        raise TimeoutError(message)

    logger.error(
        "PDF job failed in worker (%s): %s\n%s",
        err_type,
        message,
        payload.get("traceback") or "",
    )
    raise RuntimeError(f"{err_type}: {message}")


def _kill(process: BaseProcess) -> None:
    process.terminate()
    process.join(1.0)
    if process.is_alive():
        process.kill()
        process.join(1.0)


def _run_in_process(
    func: Callable[..., T],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    timeout_seconds: float,
) -> T:
    ctx = mp.get_context("spawn")
    receiver, sender = ctx.Pipe(duplex=False)
    process = ctx.Process(
        target=_process_target,
        args=(func, args, kwargs, sender),
        daemon=True,
    )
    process.start()
    sender.close()  # the child holds its own copy; EOF on receiver means it is gone
    try:
        # Read the result before joining: a large result blocks the child in
        # send() until the parent receives it, so join-then-read deadlocks.
        ready = wait([receiver, process.sentinel], timeout_seconds)
        if not ready:
            _kill(process)
            raise TimeoutError(f"PDF job exceeded {timeout_seconds}s and was terminated")
        try:
            status, payload = receiver.recv()
        except EOFError:
            process.join(1.0)
            raise RuntimeError(f"PDF job exited without a result (exitcode={process.exitcode})") from None
    finally:
        receiver.close()
    process.join(1.0)
    if status == "ok":
        return payload  # type: ignore[no-any-return]
    _raise_serialized_error(payload)
    raise AssertionError("unreachable")


def _run_in_thread(
    func: Callable[..., T],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    timeout_seconds: float,
) -> T:
    """Soft-timeout path used by tests (cannot hard-kill the worker thread)."""
    future = _get_thread_pool().submit(func, *args, **kwargs)
    try:
        return future.result(timeout=timeout_seconds)
    except TimeoutError:
        future.cancel()
        raise TimeoutError(
            f"PDF job exceeded {timeout_seconds}s (thread backend; work may continue)"
        ) from None


def execute_pdf_job(
    func: Callable[..., T],
    /,
    *args: Any,
    timeout_seconds: float,
    **kwargs: Any,
) -> T:
    """
    Run a sync PDF pipeline function under a wall-clock timeout.

    With the default ``process`` backend, the worker is terminated on timeout.
    Concurrent jobs are limited by ``PDF_MAX_CONCURRENT``.
    """
    # PDF_JOB_BACKEND: "process" (default) hard-kills a job at the timeout;
    # "thread" only stops waiting for it (tests, or where spawning is undesirable).
    backend = os.getenv("PDF_JOB_BACKEND", "process").lower()
    _job_slots.acquire()
    try:
        if backend == "thread":
            return _run_in_thread(func, args, kwargs, timeout_seconds)
        return _run_in_process(func, args, kwargs, timeout_seconds)
    finally:
        _job_slots.release()
