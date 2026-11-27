"""Shared transport helpers for the HTTP route modules."""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException, Request, UploadFile

from pdf_autofiller.errors import BatchOutputLimitError, FieldMappingError
from pdf_autofiller.models import FillReport
from pdf_autofiller.pdf_reader import InvalidPdfError, PdfPageLimitError
from pdf_autofiller.pdf_writer import UnresolvedRequiredFieldsError

from . import config
from .errors import ERROR_CATALOG, api_error
from .uploads import read_bounded_upload, require_pdf_signature, require_pdf_upload

logger = logging.getLogger(__name__)


def _sample_form_path() -> Path | None:
    for candidate in config.SAMPLE_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def _safe_header_value(field_names: list[str]) -> str:
    """Render field names as an ASCII-safe, comma-separated HTTP header value.

    Field names come from untrusted PDFs: non-ASCII and control characters
    (CR/LF would be rejected by the HTTP layer as header injection) are dropped.
    """
    joined = ",".join(field_names)
    printable = joined.encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in printable if 0x20 <= ord(ch) < 0x7F)


def _fill_report_headers(report: FillReport) -> dict[str, str]:
    """Expose fill outcome via response headers (PDF responses)."""
    return {
        "X-PDF-Fields-Written": str(len(report.written_fields)),
        "X-PDF-Fields-Skipped-Review": _safe_header_value(report.skipped_review_fields),
        "X-PDF-Fields-Skipped-Empty": _safe_header_value(report.skipped_empty_fields),
        "X-PDF-Fields-Skipped-Unwritable": _safe_header_value(report.skipped_unwritable_fields),
        "X-PDF-Fields-Display-Warnings": _safe_header_value(report.display_warnings),
        "X-PDF-Fields-AI-Assisted": _safe_header_value(report.ai_assisted_fields),
        "X-PDF-Fields-Missing-Required": _safe_header_value(report.missing_required_fields),
        # Count only: the full list can be hundreds of names (see JSON report).
        "X-PDF-Fields-Unfilled": str(len(report.unfilled_fields)),
    }


def _wants_json_fill_report(request: Request) -> bool:
    """True when the client prefers a JSON fill report over a raw PDF body."""
    accept = request.headers.get("accept", "")
    if not accept:
        return False

    def quality(media_type: str) -> tuple[float, int]:
        best = (0.0, len(accept))
        best_specificity = -1
        target_type, _target_subtype = media_type.split("/", 1)
        for index, raw_part in enumerate(accept.split(",")):
            sections = [section.strip() for section in raw_part.split(";")]
            candidate = sections[0].lower()
            matches = candidate in {media_type, f"{target_type}/*", "*/*"}
            if not matches:
                continue
            q = 1.0
            for parameter in sections[1:]:
                name, separator, value = parameter.partition("=")
                if separator and name.strip().lower() == "q":
                    try:
                        q = max(0.0, min(1.0, float(value.strip())))
                    except ValueError:
                        q = 0.0
            specificity = 2 if candidate == media_type else 1 if candidate.endswith("/*") else 0
            # Exact entries must override wildcards even when they explicitly
            # reject a representation with q=0.
            if specificity > best_specificity or (
                specificity == best_specificity and (q > best[0] or (q == best[0] and index < best[1]))
            ):
                best = (q, index)
                best_specificity = specificity
        return best

    json_quality, json_index = quality("application/json")
    pdf_quality, pdf_index = quality("application/pdf")
    if json_quality <= 0:
        return False
    if json_quality != pdf_quality:
        return json_quality > pdf_quality
    if json_index == pdf_index:
        return False  # wildcard-only ties keep the binary PDF default
    return json_index < pdf_index


def _audit_log_fill(
    request: Request,
    *,
    fields_total: int,
    report: FillReport,
    missing_required: int,
    use_semantic_inference: bool,
    allow_fallback_mapping: bool,
    response_mode: str,
) -> None:
    """Emit a structured, PII-free audit record for a completed fill."""
    request_id = getattr(request.state, "request_id", "unknown")
    logger.info(
        "audit action=fill request_id=%s auth=%s fields_total=%d fields_written=%d "
        "fields_review_skipped=%d fields_empty_skipped=%d fields_unwritable=%d "
        "missing_required=%d semantic_inference=%s fallback_mapping=%s response_mode=%s",
        request_id,
        "enabled" if config.API_AUTH_ENABLED else "disabled",
        fields_total,
        len(report.written_fields),
        len(report.skipped_review_fields),
        len(report.skipped_empty_fields),
        len(report.skipped_unwritable_fields),
        missing_required,
        use_semantic_inference,
        allow_fallback_mapping,
        response_mode,
    )


@contextmanager
def _unexpected_errors(code: str) -> Iterator[None]:
    """Pass API errors through; log anything else and answer with a generic 500 ``code``."""
    try:
        yield
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unhandled error (%s)", code)
        raise api_error(status_code=500, code=code, message=ERROR_CATALOG[code][1]) from exc


async def _save_pdf_upload(pdf_file: UploadFile, temp_dir: tempfile.TemporaryDirectory) -> Path:
    """Validate the upload (type, size, %PDF- header) and write it into ``temp_dir``."""
    require_pdf_upload(pdf_file)
    content = await read_bounded_upload(pdf_file)
    require_pdf_signature(content)
    input_path = Path(temp_dir.name) / "input.pdf"
    input_path.write_bytes(content)
    return input_path


@contextmanager
def _pdf_job_errors() -> Iterator[None]:
    """Translate pipeline job failures into client-facing API errors."""
    try:
        yield
    except UnresolvedRequiredFieldsError as exc:
        raise api_error(
            status_code=422,
            code="required_fields_unresolved",
            message="Required fields unresolved",
            details={"missing_fields": exc.missing_fields, "skipped_fields": exc.skipped_fields},
        ) from exc
    except TimeoutError as exc:
        raise api_error(
            status_code=503,
            code="pdf_processing_timeout",
            message="PDF processing exceeded the time limit",
            details={"timeout_seconds": config.PDF_READ_TIMEOUT_SECONDS},
        ) from exc
    except PdfPageLimitError as exc:
        raise api_error(
            status_code=413,
            code="pdf_too_many_pages",
            message="PDF exceeds the maximum allowed page count",
            details={"max_pages": exc.max_pages, "num_pages": exc.num_pages},
        ) from exc
    except InvalidPdfError as exc:
        raise api_error(
            status_code=422,
            code="invalid_pdf",
            message="PDF could not be parsed",
            details={"reason": str(exc)},
        ) from exc
    except FieldMappingError as exc:
        raise api_error(
            status_code=422,
            code="invalid_field_mapping",
            message=str(exc),
        ) from exc
    except BatchOutputLimitError as exc:
        raise api_error(
            status_code=413,
            code="batch_output_too_large",
            message=ERROR_CATALOG["batch_output_too_large"][1],
            details={
                "generated_bytes": exc.generated_bytes,
                "max_response_bytes": exc.max_bytes,
            },
        ) from exc


def _require_consistent_options(*, strict: bool, allow_fallback_mapping: bool) -> None:
    if strict and allow_fallback_mapping:
        raise api_error(
            status_code=422,
            code="conflicting_options",
            message=ERROR_CATALOG["conflicting_options"][1],
        )
