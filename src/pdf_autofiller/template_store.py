"""Durable template, mapping, job, and artifact storage for the product API.

The PDF engine remains storage-agnostic. This module is the local/self-hosted
adapter: SQLite stores metadata and a private filesystem directory stores PDF
objects. A managed deployment can replace this boundary with PostgreSQL and
S3-compatible implementations without changing the fill pipeline.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

TemplateStatus = Literal["draft", "published"]
JobStatus = Literal["running", "completed", "failed"]


def _now() -> str:
    return datetime.now(UTC).isoformat()


class StoredTemplateVersion(BaseModel):
    template_id: str
    name: str
    version: int
    revision: int
    status: TemplateStatus
    source_sha256: str
    source_key: str
    template: dict[str, Any]
    mapping: dict[str, str]
    created_at: str
    published_at: str | None = None


class StoredJob(BaseModel):
    id: str
    template_id: str
    template_version: int
    status: JobStatus
    report: dict[str, Any] | None = None
    artifact_key: str | None = None
    error_code: str | None = None
    created_at: str
    completed_at: str | None = None


class StoredCorrection(BaseModel):
    id: str
    template_id: str
    template_version: int
    field_name: str
    suggested_key: str | None = None
    approved_key: str | None = None
    created_at: str


class TemplateStoreError(RuntimeError):
    """Base error raised by the durable template store."""


class TemplateNotFoundError(TemplateStoreError):
    pass


class TemplateConflictError(TemplateStoreError):
    pass


class TemplateStateError(TemplateStoreError):
    pass


class JobNotFoundError(TemplateStoreError):
    pass


class LocalObjectStore:
    """Content-addressed source PDFs and job-addressed output artifacts."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.sources = self.root / "objects" / "sources"
        self.artifacts = self.root / "objects" / "artifacts"
        self.sources.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.artifacts.mkdir(parents=True, exist_ok=True, mode=0o700)

    def put_source(self, content: bytes) -> tuple[str, str]:
        digest = hashlib.sha256(content).hexdigest()
        key = f"sources/{digest}.pdf"
        destination = self.sources / f"{digest}.pdf"
        if not destination.exists():
            self._atomic_write(destination, content)
        return key, digest

    def put_artifact(self, job_id: str, content: bytes) -> str:
        safe_id = str(uuid.UUID(job_id))
        key = f"artifacts/{safe_id}.pdf"
        self._atomic_write(self.artifacts / f"{safe_id}.pdf", content)
        return key

    def resolve(self, key: str) -> Path:
        kind, separator, filename = key.partition("/")
        if separator != "/" or kind not in {"sources", "artifacts"} or Path(filename).name != filename:
            raise ValueError("Invalid object key")
        path = (self.root / "objects" / kind / filename).resolve()
        expected_parent = (self.root / "objects" / kind).resolve()
        if path.parent != expected_parent:
            raise ValueError("Invalid object key")
        return path

    @staticmethod
    def _atomic_write(destination: Path, content: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(prefix=".upload-", dir=destination.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            temporary.chmod(0o600)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


class SqliteTemplateRepository:
    """Transactional metadata repository for a single self-hosted deployment."""

    def __init__(self, database_path: Path):
        self.database_path = database_path.resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS template_versions (
                    template_id TEXT NOT NULL REFERENCES templates(id) ON DELETE CASCADE,
                    version INTEGER NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 1,
                    status TEXT NOT NULL CHECK(status IN ('draft', 'published')),
                    source_sha256 TEXT NOT NULL,
                    source_key TEXT NOT NULL,
                    template_json TEXT NOT NULL,
                    mapping_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    published_at TEXT,
                    PRIMARY KEY (template_id, version)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS one_draft_per_template
                    ON template_versions(template_id) WHERE status = 'draft';
                CREATE TABLE IF NOT EXISTS fill_jobs (
                    id TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL,
                    template_version INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('running', 'completed', 'failed')),
                    report_json TEXT,
                    artifact_key TEXT,
                    error_code TEXT,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY(template_id, template_version)
                        REFERENCES template_versions(template_id, version)
                );
                CREATE INDEX IF NOT EXISTS jobs_by_template
                    ON fill_jobs(template_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS mapping_corrections (
                    id TEXT PRIMARY KEY,
                    template_id TEXT NOT NULL,
                    template_version INTEGER NOT NULL,
                    field_name TEXT NOT NULL,
                    suggested_key TEXT,
                    approved_key TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(template_id, template_version)
                        REFERENCES template_versions(template_id, version)
                );
                CREATE INDEX IF NOT EXISTS corrections_by_template
                    ON mapping_corrections(template_id, created_at DESC);
                """
            )

    def create_template(
        self,
        *,
        name: str,
        source_sha256: str,
        source_key: str,
        template: dict[str, Any],
        mapping: dict[str, str],
    ) -> StoredTemplateVersion:
        template_id = str(uuid.uuid4())
        created_at = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO templates(id, name, created_at) VALUES (?, ?, ?)",
                (template_id, name, created_at),
            )
            connection.execute(
                """INSERT INTO template_versions(
                       template_id, version, revision, status, source_sha256, source_key,
                       template_json, mapping_json, created_at
                   ) VALUES (?, 1, 1, 'draft', ?, ?, ?, ?, ?)""",
                (
                    template_id,
                    source_sha256,
                    source_key,
                    json.dumps(template, separators=(",", ":")),
                    json.dumps(mapping, separators=(",", ":")),
                    created_at,
                ),
            )
            connection.commit()
        return self.get_version(template_id, 1)

    def list_templates(self) -> list[StoredTemplateVersion]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT tv.*, t.name FROM template_versions tv
                   JOIN templates t ON t.id = tv.template_id
                   WHERE tv.version = (
                       SELECT MAX(latest.version) FROM template_versions latest
                       WHERE latest.template_id = tv.template_id
                   )
                   ORDER BY t.created_at DESC"""
            ).fetchall()
        return [self._version_from_row(row) for row in rows]

    def create_version(
        self,
        template_id: str,
        *,
        source_sha256: str,
        source_key: str,
        template: dict[str, Any],
        mapping: dict[str, str],
    ) -> StoredTemplateVersion:
        """Create the next draft after a published version.

        Only one draft may exist at a time. Published rows remain immutable so
        historical jobs always name the exact mapping and PDF that produced them.
        """
        created_at = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                """SELECT version, status FROM template_versions
                   WHERE template_id = ? ORDER BY version DESC LIMIT 1""",
                (template_id,),
            ).fetchone()
            if latest is None:
                raise TemplateNotFoundError(template_id)
            if latest["status"] == "draft":
                raise TemplateStateError("Finish or publish the current draft before creating a version")
            version = int(latest["version"]) + 1
            connection.execute(
                """INSERT INTO template_versions(
                       template_id, version, revision, status, source_sha256, source_key,
                       template_json, mapping_json, created_at
                   ) VALUES (?, ?, 1, 'draft', ?, ?, ?, ?, ?)""",
                (
                    template_id,
                    version,
                    source_sha256,
                    source_key,
                    json.dumps(template, separators=(",", ":")),
                    json.dumps(mapping, separators=(",", ":")),
                    created_at,
                ),
            )
            connection.commit()
        return self.get_version(template_id, version)

    def get_latest(self, template_id: str) -> StoredTemplateVersion:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT tv.*, t.name FROM template_versions tv
                   JOIN templates t ON t.id = tv.template_id
                   WHERE tv.template_id = ? ORDER BY tv.version DESC LIMIT 1""",
                (template_id,),
            ).fetchone()
        if row is None:
            raise TemplateNotFoundError(template_id)
        return self._version_from_row(row)

    def get_version(self, template_id: str, version: int) -> StoredTemplateVersion:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT tv.*, t.name FROM template_versions tv
                   JOIN templates t ON t.id = tv.template_id
                   WHERE tv.template_id = ? AND tv.version = ?""",
                (template_id, version),
            ).fetchone()
        if row is None:
            raise TemplateNotFoundError(template_id)
        return self._version_from_row(row)

    def update_mapping(
        self,
        template_id: str,
        *,
        mapping: dict[str, str],
        expected_revision: int,
    ) -> StoredTemplateVersion:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                """SELECT version, revision, status, mapping_json FROM template_versions
                   WHERE template_id = ? ORDER BY version DESC LIMIT 1""",
                (template_id,),
            ).fetchone()
            if latest is None:
                raise TemplateNotFoundError(template_id)
            if latest["status"] != "draft":
                raise TemplateStateError("The latest template version is already published")
            if latest["revision"] != expected_revision:
                raise TemplateConflictError("The mapping draft changed; reload before saving")
            previous_mapping = json.loads(latest["mapping_json"])
            connection.execute(
                """UPDATE template_versions SET mapping_json = ?, revision = revision + 1
                   WHERE template_id = ? AND version = ?""",
                (json.dumps(mapping, separators=(",", ":")), template_id, latest["version"]),
            )
            changed_fields = sorted(set(previous_mapping) | set(mapping))
            for field_name in changed_fields:
                suggested_key = previous_mapping.get(field_name)
                approved_key = mapping.get(field_name)
                if suggested_key == approved_key:
                    continue
                connection.execute(
                    """INSERT INTO mapping_corrections(
                           id, template_id, template_version, field_name,
                           suggested_key, approved_key, created_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        template_id,
                        latest["version"],
                        field_name,
                        suggested_key,
                        approved_key,
                        _now(),
                    ),
                )
            connection.commit()
            version = int(latest["version"])
        return self.get_version(template_id, version)

    def publish(self, template_id: str, *, expected_revision: int) -> StoredTemplateVersion:
        published_at = _now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            latest = connection.execute(
                """SELECT version, revision, status FROM template_versions
                   WHERE template_id = ? ORDER BY version DESC LIMIT 1""",
                (template_id,),
            ).fetchone()
            if latest is None:
                raise TemplateNotFoundError(template_id)
            if latest["status"] != "draft":
                raise TemplateStateError("The latest template version is already published")
            if latest["revision"] != expected_revision:
                raise TemplateConflictError("The mapping draft changed; reload before publishing")
            connection.execute(
                """UPDATE template_versions SET status = 'published', published_at = ?
                   WHERE template_id = ? AND version = ?""",
                (published_at, template_id, latest["version"]),
            )
            connection.commit()
            version = int(latest["version"])
        return self.get_version(template_id, version)

    def get_published(self, template_id: str) -> StoredTemplateVersion:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT tv.*, t.name FROM template_versions tv
                   JOIN templates t ON t.id = tv.template_id
                   WHERE tv.template_id = ? AND tv.status = 'published'
                   ORDER BY tv.version DESC LIMIT 1""",
                (template_id,),
            ).fetchone()
        if row is None:
            if not self._template_exists(template_id):
                raise TemplateNotFoundError(template_id)
            raise TemplateStateError("Template has no published version")
        return self._version_from_row(row)

    def create_job(self, template_id: str, template_version: int) -> StoredJob:
        job_id = str(uuid.uuid4())
        created_at = _now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO fill_jobs(
                       id, template_id, template_version, status, created_at
                   ) VALUES (?, ?, ?, 'running', ?)""",
                (job_id, template_id, template_version, created_at),
            )
            connection.commit()
        return self.get_job(job_id)

    def complete_job(self, job_id: str, *, report: dict[str, Any], artifact_key: str) -> StoredJob:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE fill_jobs SET status = 'completed', report_json = ?, artifact_key = ?,
                       completed_at = ? WHERE id = ? AND status = 'running'""",
                (json.dumps(report, separators=(",", ":")), artifact_key, _now(), job_id),
            )
            connection.commit()
        if cursor.rowcount != 1:
            raise JobNotFoundError(job_id)
        return self.get_job(job_id)

    def fail_job(self, job_id: str, *, error_code: str) -> StoredJob:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE fill_jobs SET status = 'failed', error_code = ?, completed_at = ?
                   WHERE id = ? AND status = 'running'""",
                (error_code, _now(), job_id),
            )
            connection.commit()
        if cursor.rowcount != 1:
            raise JobNotFoundError(job_id)
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> StoredJob:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM fill_jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFoundError(job_id)
        return StoredJob(
            id=row["id"],
            template_id=row["template_id"],
            template_version=row["template_version"],
            status=row["status"],
            report=json.loads(row["report_json"]) if row["report_json"] else None,
            artifact_key=row["artifact_key"],
            error_code=row["error_code"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    def list_corrections(self, template_id: str) -> list[StoredCorrection]:
        if not self._template_exists(template_id):
            raise TemplateNotFoundError(template_id)
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM mapping_corrections
                   WHERE template_id = ? ORDER BY created_at, id""",
                (template_id,),
            ).fetchall()
        return [
            StoredCorrection(
                id=row["id"],
                template_id=row["template_id"],
                template_version=row["template_version"],
                field_name=row["field_name"],
                suggested_key=row["suggested_key"],
                approved_key=row["approved_key"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def _template_exists(self, template_id: str) -> bool:
        with self._connect() as connection:
            row = connection.execute("SELECT 1 FROM templates WHERE id = ?", (template_id,)).fetchone()
        return row is not None

    @staticmethod
    def _version_from_row(row: sqlite3.Row) -> StoredTemplateVersion:
        return StoredTemplateVersion(
            template_id=row["template_id"],
            name=row["name"],
            version=row["version"],
            revision=row["revision"],
            status=row["status"],
            source_sha256=row["source_sha256"],
            source_key=row["source_key"],
            template=json.loads(row["template_json"]),
            mapping=json.loads(row["mapping_json"]),
            created_at=row["created_at"],
            published_at=row["published_at"],
        )


class TemplateStore:
    """Facade combining metadata and object storage boundaries."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.objects = LocalObjectStore(self.root)
        self.repository = SqliteTemplateRepository(self.root / "metadata.sqlite3")
