"""
Process-isolated execution for untrusted PDF parsing.

Why a process and not a thread: CPython cannot interrupt a running thread.
``asyncio.wait_for`` around ``asyncio.to_thread`` cancels the *await*, not the
work — the endpoint returns 503 while the pipeline keeps running on a pool
thread forever. A handful of crafted PDFs exhaust the executor, after which the
service stops serving while still passing its own health check.

A child process can be killed. It also contains parser memory blowups and hard
crashes, which a thread shares with the whole service.

Cost is low here because only a filesystem path crosses the boundary, never the
document bytes. When multiprocessing is unavailable (restricted sandboxes, some
frozen builds) this degrades to in-process execution and says so in the log,
rather than failing closed on a capability the caller cannot influence.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import traceback
from typing import Any, Callable, Optional

from .errors import PdfAutofillerError, PdfProcessingTimeoutError

logger = logging.getLogger(__name__)

# "spawn" would re-import the world per call; "fork" is cheap and this process
# holds no threads or handles the child must not inherit at call time.
_MP_METHOD = "fork" if "fork" in multiprocessing.get_all_start_methods() else "spawn"


class _ErrorEnvelope:
    """A domain error flattened for transport across the process boundary.

    Exceptions are not reliably picklable: our error classes take structured
    constructor arguments, so the default ``cls(*args)`` reconstruction would
    raise ``TypeError`` in the parent and mask the real failure. Sending the
    wire-level facts and rebuilding on the far side keeps the contract intact.
    """

    __slots__ = ("code", "status_code", "message", "details", "kind")

    def __init__(self, code: str, status_code: int, message: str, details: dict[str, Any], kind: str):
        self.code = code
        self.status_code = status_code
        self.message = message
        self.details = details
        self.kind = kind


class RemotePdfAutofillerError(PdfAutofillerError):
    """A domain error re-raised in the parent after crossing a process boundary."""

    def __init__(self, envelope: _ErrorEnvelope):
        self.code = envelope.code
        self.status_code = envelope.status_code
        self._details = envelope.details
        self.kind = envelope.kind
        super().__init__(envelope.message)

    def details(self) -> dict[str, Any]:
        return self._details


def _child_entrypoint(conn, func: Callable[..., Any], args: tuple, kwargs: dict) -> None:
    """Run ``func`` in the child and send back either a result or an error."""
    try:
        conn.send(("ok", func(*args, **kwargs)))
    except PdfAutofillerError as exc:
        conn.send(
            (
                "domain_error",
                _ErrorEnvelope(
                    code=exc.code,
                    status_code=exc.status_code,
                    message=str(exc),
                    details=exc.details(),
                    kind=type(exc).__name__,
                ),
            )
        )
    except Exception as exc:
        conn.send(("error", f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"))
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_isolated(
    func: Callable[..., Any],
    *args: Any,
    timeout: float,
    enabled: bool = True,
    **kwargs: Any,
) -> Any:
    """
    Run ``func`` in a killable child process under a wall-clock timeout.

    Args:
        func: A module-level callable (must be importable in the child)
        timeout: Seconds before the child is terminated
        enabled: Set False to run in-process (tests, single-user CLI runs)

    Raises:
        PdfProcessingTimeoutError: If the child exceeded ``timeout``
        RemotePdfAutofillerError: If the child raised a domain error
        RuntimeError: If the child died or failed unexpectedly
    """
    if not enabled:
        return func(*args, **kwargs)

    try:
        # get_context is typed as returning BaseContext, which does not declare
        # Process/Pipe; the concrete fork/spawn contexts do.
        ctx: Any = multiprocessing.get_context(_MP_METHOD)
        parent_conn, child_conn = ctx.Pipe(duplex=False)
        process = ctx.Process(
            target=_child_entrypoint, args=(child_conn, func, args, kwargs), daemon=True
        )
        process.start()
    except Exception as exc:
        logger.warning(
            "Process isolation unavailable (%s); running in-process. "
            "A hostile PDF can no longer be interrupted on timeout.",
            exc,
        )
        return func(*args, **kwargs)

    child_conn.close()
    try:
        if not parent_conn.poll(timeout):
            _terminate(process)
            raise PdfProcessingTimeoutError(timeout)

        try:
            status, payload = parent_conn.recv()
        except EOFError as exc:
            # The child died without sending: a segfault or OOM kill.
            raise RuntimeError(
                f"PDF worker exited unexpectedly (exit code {process.exitcode})"
            ) from exc

        if status == "ok":
            return payload
        if status == "domain_error":
            raise RemotePdfAutofillerError(payload)
        raise RuntimeError(f"PDF worker failed: {payload}")
    finally:
        try:
            parent_conn.close()
        except Exception:
            pass
        _terminate(process)


def _terminate(process: Optional[Any]) -> None:
    """Stop a worker, escalating to SIGKILL if it ignores termination."""
    if process is None:
        return
    try:
        if process.is_alive():
            process.terminate()
            process.join(timeout=2.0)
        if process.is_alive():
            process.kill()
            process.join(timeout=2.0)
    except Exception:
        logger.debug("Failed to terminate PDF worker", exc_info=True)
    finally:
        try:
            process.close()
        except Exception:
            pass


def isolation_supported() -> bool:
    """Whether this platform can actually fork/spawn a worker."""
    return hasattr(os, "fork") or _MP_METHOD == "spawn"
