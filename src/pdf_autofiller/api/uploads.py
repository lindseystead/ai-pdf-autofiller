"""Upload validation helpers."""

from __future__ import annotations

from fastapi import UploadFile

from . import config
from .errors import api_error


async def read_bounded_upload(upload: UploadFile, max_bytes: int | None = None) -> bytes:
    """Read an upload in chunks and reject payloads before they fully buffer."""
    limit = config.MAX_UPLOAD_BYTES if max_bytes is None else max_bytes
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(config.UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > limit:
            raise api_error(
                status_code=413,
                code="payload_too_large",
                message="PDF exceeds MAX_UPLOAD_BYTES limit",
                details={"max_upload_bytes": limit},
            )
        chunks.append(chunk)
    return b"".join(chunks)


def require_pdf_upload(upload: UploadFile) -> None:
    """Reject non-PDF content types early."""
    if upload.content_type not in ("application/pdf", "application/octet-stream"):
        raise api_error(
            status_code=415,
            code="unsupported_media_type",
            message="Expected a PDF upload",
        )


def require_pdf_signature(content: bytes) -> None:
    """Reject uploads that do not start with a PDF header."""
    if not content.startswith(b"%PDF-"):
        raise api_error(
            status_code=415,
            code="invalid_pdf_signature",
            message="Uploaded file is not a valid PDF",
        )
