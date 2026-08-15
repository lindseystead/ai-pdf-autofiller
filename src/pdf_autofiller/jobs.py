"""
Background batch jobs.

Filling 200 onboarding packets over a synchronous single-document endpoint means
200 sequential requests, each racing the per-request wall clock. A batch submits
once, returns an ID, and reports per-item status.

This is an in-process registry backed by a bounded thread pool, not a queue
service. That is a deliberate ceiling: it keeps the zero-dependency install
intact and matches the scale this tool actually runs at (one operator, one box,
a few hundred documents). Jobs do not survive a restart, and the API says so in
the job payload rather than implying durability it does not have. Moving to a
real broker is a drop-in replacement behind :func:`submit_batch`.
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Keep finished jobs around long enough to be collected, but bounded so a
# long-running server cannot accumulate them without limit.
_MAX_RETAINED_JOBS = 200


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BatchItemResult(BaseModel):
    """Outcome for one document in a batch."""

    index: int
    name: str
    status: str = Field(description="pending | running | succeeded | failed")
    output_path: Optional[str] = None
    fields_written: int = 0
    fields_skipped: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None


class BatchJob(BaseModel):
    """State of a submitted batch."""

    job_id: str
    status: str = Field(description="queued | running | completed")
    total: int
    succeeded: int = 0
    failed: int = 0
    created_at: str = Field(default_factory=_utcnow)
    completed_at: Optional[str] = None
    items: list[BatchItemResult] = Field(default_factory=list)
    durable: bool = Field(
        default=False,
        description="False: this job lives in server memory and is lost on restart",
    )


class _JobRegistry:
    """Thread-safe job table with bounded retention."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: "OrderedDict[str, BatchJob]" = OrderedDict()
        self._executor: Optional[ThreadPoolExecutor] = None

    def executor(self) -> ThreadPoolExecutor:
        with self._lock:
            if self._executor is None:
                self._executor = ThreadPoolExecutor(
                    max_workers=4, thread_name_prefix="pdf-batch"
                )
            return self._executor

    def create(self, total: int, names: list[str]) -> BatchJob:
        job = BatchJob(
            job_id=uuid.uuid4().hex,
            status="queued",
            total=total,
            items=[
                BatchItemResult(index=i, name=name, status="pending")
                for i, name in enumerate(names)
            ],
        )
        with self._lock:
            self._jobs[job.job_id] = job
            while len(self._jobs) > _MAX_RETAINED_JOBS:
                self._jobs.popitem(last=False)
        return job

    def get(self, job_id: str) -> Optional[BatchJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.model_copy(deep=True) if job else None

    def list(self) -> list[BatchJob]:
        with self._lock:
            return [job.model_copy(deep=True) for job in reversed(self._jobs.values())]

    def update(self, job_id: str, mutate: Callable[[BatchJob], None]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                mutate(job)


_registry = _JobRegistry()


def get_job(job_id: str) -> Optional[BatchJob]:
    """Return a snapshot of a job's state, or None if unknown."""
    return _registry.get(job_id)


def list_jobs() -> list[BatchJob]:
    """Return snapshots of retained jobs, newest first."""
    return _registry.list()


def submit_batch(
    items: list[dict[str, Any]],
    worker: Callable[[dict[str, Any]], dict[str, Any]],
) -> BatchJob:
    """
    Run ``worker`` over ``items`` in the background and return the job record.

    ``worker`` receives one item dict and returns a result dict carrying
    ``output_path``, ``fields_written``, and ``fields_skipped``. Raising is the
    way to fail a single item: the failure is recorded against that item and the
    rest of the batch continues, because one bad document should not discard 199
    good ones.
    """
    job = _registry.create(len(items), [str(item.get("name", f"item-{i}")) for i, item in enumerate(items)])

    def run() -> None:
        def start(j: BatchJob) -> None:
            j.status = "running"

        _registry.update(job.job_id, start)
        for index, item in enumerate(items):
            def mark_running(j: BatchJob, i: int = index) -> None:
                j.items[i].status = "running"

            _registry.update(job.job_id, mark_running)
            try:
                result = worker(item)
            except Exception as exc:
                code = getattr(exc, "code", type(exc).__name__)
                message = str(exc)
                logger.warning("Batch item %d failed: %s", index, message)

                def mark_failed(j: BatchJob, i: int = index, c: str = code, m: str = message) -> None:
                    j.items[i].status = "failed"
                    j.items[i].error_code = c
                    j.items[i].error_message = m
                    j.failed += 1

                _registry.update(job.job_id, mark_failed)
                continue

            def mark_ok(j: BatchJob, i: int = index, r: dict[str, Any] = result) -> None:
                j.items[i].status = "succeeded"
                j.items[i].output_path = r.get("output_path")
                j.items[i].fields_written = int(r.get("fields_written", 0))
                j.items[i].fields_skipped = int(r.get("fields_skipped", 0))
                j.succeeded += 1

            _registry.update(job.job_id, mark_ok)

        def finish(j: BatchJob) -> None:
            j.status = "completed"
            j.completed_at = _utcnow()

        _registry.update(job.job_id, finish)

    _registry.executor().submit(run)
    return job
