"""HTTP route handlers."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.background import BackgroundTask

from pdf_autofiller import __version__
from pdf_autofiller.mapping import alias_pack_status
from pdf_autofiller.models import FillReport
from pdf_autofiller.pdf_reader import PdfPageLimitError, read_pdf
from pdf_autofiller.pdf_writer import UnresolvedRequiredFieldsError
from pdf_autofiller.pipeline import (
    run_fill_pipeline,
    run_preview_pipeline,
    semantic_provider_status,
)
from pdf_autofiller.playground import PLAYGROUND_HTML

from . import config
from .errors import (
    MUTATING_ERROR_CODES,
    api_error,
    openapi_error_responses,
)
from .schemas import (
    FillReportResponse,
    HealthResponse,
    InspectField,
    InspectResponse,
    PreviewDecision,
    PreviewResponse,
    VersionResponse,
)
from .security import guard_mutating_request
from .uploads import read_bounded_upload, require_pdf_signature, require_pdf_upload

logger = logging.getLogger(__name__)

router = APIRouter()


def _sample_form_path() -> Path | None:
    for candidate in config.SAMPLE_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


def _safe_header_value(field_names: list[str]) -> str:
    """Render field names as an ASCII-safe, comma-separated HTTP header value."""
    joined = ",".join(field_names)
    return joined.encode("ascii", "ignore").decode("ascii")


def _fill_report_headers(report: FillReport) -> dict[str, str]:
    """Expose fill outcome via response headers (PDF responses)."""
    return {
        "X-PDF-Fields-Written": str(len(report.written_fields)),
        "X-PDF-Fields-Skipped-Review": _safe_header_value(report.skipped_review_fields),
        "X-PDF-Fields-Skipped-Empty": _safe_header_value(report.skipped_empty_fields),
        "X-PDF-Fields-Skipped-Unwritable": _safe_header_value(
            report.skipped_unwritable_fields
        ),
    }


def _wants_json_fill_report(request: Request) -> bool:
    """True when the client prefers a JSON fill report over a raw PDF body."""
    accept = request.headers.get("accept", "")
    if not accept:
        return False
    # Explicit JSON without PDF wins; otherwise keep binary PDF as default.
    parts = [part.strip().split(";")[0].lower() for part in accept.split(",")]
    if "application/json" in parts and "application/pdf" not in parts:
        return True
    return bool(parts and parts[0] == "application/json")


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


def _parse_user_data(user_data: str) -> dict[str, Any]:
    try:
        parsed = json.loads(user_data)
    except json.JSONDecodeError as exc:
        raise api_error(
            status_code=422,
            code="invalid_user_data_json",
            message="Invalid user_data JSON",
            details={"reason": str(exc)},
        ) from exc
    if not isinstance(parsed, dict):
        raise api_error(
            status_code=422,
            code="invalid_user_data_type",
            message="user_data must be a JSON object",
        )
    return parsed


@router.get("/")
def root() -> RedirectResponse:
    """Redirect browsers to the interactive playground."""
    return RedirectResponse(url="/playground")


@router.get("/playground", response_class=HTMLResponse)
def playground_page() -> HTMLResponse:
    """Serve the browser playground for trying fills without curl."""
    return HTMLResponse(content=PLAYGROUND_HTML)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    checks = {
        "auth": (
            "enabled"
            if config.API_AUTH_ENABLED and config.API_AUTH_TOKEN
            else "disabled"
            if not config.API_AUTH_ENABLED
            else "misconfigured"
        ),
        "semantic_provider": semantic_provider_status(),
        "rate_limit": (
            "in_process"
            if config.RATE_LIMIT_PER_MINUTE > 0
            else "disabled"
        ),
        **alias_pack_status(),
    }
    status = "ok" if checks["auth"] != "misconfigured" else "degraded"
    return HealthResponse(
        status=status,
        service="pdf-autofiller",
        version=__version__,
        checks=checks,
    )


@router.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(service="pdf-autofiller", version=__version__)


@router.get("/samples/sample_form.pdf")
def sample_form_pdf() -> FileResponse:
    """Serve the bundled sample AcroForm for playground one-click demos."""
    sample = _sample_form_path()
    if sample is None:
        raise api_error(
            status_code=404,
            code="sample_not_found",
            message="Sample PDF is not bundled in this deployment",
        )
    return FileResponse(
        path=sample,
        media_type="application/pdf",
        filename="sample_form.pdf",
    )


@router.post(
    "/inspect",
    response_model=InspectResponse,
    responses=openapi_error_responses(
        *MUTATING_ERROR_CODES,
        "pdf_inspect_failed",
    ),
)
async def inspect_pdf(
    request: Request,
    pdf_file: UploadFile = File(...),
) -> InspectResponse:
    """List AcroForm fields so clients can draft matching JSON without guessing."""
    temp_dir = None
    try:
        guard_mutating_request(request)
        require_pdf_upload(pdf_file)
        content = await read_bounded_upload(pdf_file)
        require_pdf_signature(content)

        temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-inspect-")
        input_path = Path(temp_dir.name) / "input.pdf"
        input_path.write_bytes(content)

        try:
            structure = await asyncio.wait_for(
                asyncio.to_thread(
                    lambda: read_pdf(input_path, max_pages=config.MAX_PDF_PAGES)
                ),
                timeout=config.PDF_READ_TIMEOUT_SECONDS,
            )
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

        fields = [
            InspectField(
                name=field.name,
                field_type=field.field_type,
                required=field.required,
                page_number=field.page_number,
                current_value=field.value,
            )
            for field in structure.form_fields
        ]
        return InspectResponse(
            pages=structure.metadata.num_pages,
            field_count=len(fields),
            fields=fields,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("PDF inspect request failed")
        raise api_error(
            status_code=500,
            code="pdf_inspect_failed",
            message="PDF inspect failed",
        ) from exc
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
        await pdf_file.close()


@router.post(
    "/preview",
    response_model=PreviewResponse,
    responses=openapi_error_responses(
        *MUTATING_ERROR_CODES,
        "invalid_user_data_json",
        "invalid_user_data_type",
        "pdf_preview_failed",
    ),
)
async def preview_pdf(
    request: Request,
    pdf_file: UploadFile = File(...),
    user_data: str = Form(...),
    strict: bool = Form(True),
    allow_fallback_mapping: bool = Form(False),
    use_semantic_inference: bool = Form(False),
) -> PreviewResponse:
    """Return mapping decisions without writing a PDF (inspect → map debug loop)."""
    temp_dir = None
    try:
        guard_mutating_request(request)
        require_pdf_upload(pdf_file)
        parsed_user_data = _parse_user_data(user_data)
        content = await read_bounded_upload(pdf_file)
        require_pdf_signature(content)

        temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-preview-")
        input_path = Path(temp_dir.name) / "input.pdf"
        input_path.write_bytes(content)

        try:
            mapping_result, field_count, page_count = await asyncio.wait_for(
                asyncio.to_thread(
                    run_preview_pipeline,
                    input_path,
                    parsed_user_data,
                    strict=strict,
                    allow_fallback_mapping=allow_fallback_mapping,
                    use_semantic_inference=use_semantic_inference,
                    max_pages=config.MAX_PDF_PAGES,
                ),
                timeout=config.PDF_READ_TIMEOUT_SECONDS,
            )
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

        decisions = [
            PreviewDecision(
                field_name=d.field_name,
                semantic_meaning=d.semantic_meaning,
                selected_value=d.selected_value,
                confidence=d.confidence,
                reason=d.reason,
                requires_review=d.requires_review,
            )
            for d in mapping_result.decisions
        ]
        return PreviewResponse(
            pages=page_count,
            field_count=field_count,
            decisions=decisions,
            missing_required=list(mapping_result.missing_required),
            unmapped_user_keys=list(mapping_result.unmapped_user_keys),
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("PDF preview request failed")
        raise api_error(
            status_code=500,
            code="pdf_preview_failed",
            message="PDF preview failed",
        ) from exc
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
        await pdf_file.close()


@router.post(
    "/fill",
    responses={
        200: {
            "content": {
                "application/pdf": {"description": "Filled PDF binary"},
                "application/json": {
                    "description": (
                        "Fill report JSON including base64 PDF when "
                        "Accept prefers application/json"
                    ),
                    "schema": FillReportResponse.model_json_schema(),
                },
            },
        },
        **openapi_error_responses(
            *MUTATING_ERROR_CODES,
            "invalid_user_data_json",
            "invalid_user_data_type",
            "required_fields_unresolved",
            "pdf_fill_failed",
        ),
    },
)
async def fill(
    request: Request,
    pdf_file: UploadFile = File(...),
    user_data: str = Form(...),
    strict: bool = Form(True),
    allow_fallback_mapping: bool = Form(False),
    use_semantic_inference: bool = Form(False),
    flatten: bool = Form(False),
) -> Response:
    """Fill a PDF form from uploaded file and user data."""
    temp_dir = None
    response_started = False

    try:
        guard_mutating_request(request)
        require_pdf_upload(pdf_file)
        parsed_user_data = _parse_user_data(user_data)

        temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-")
        temp_path = Path(temp_dir.name)
        input_path = temp_path / "input.pdf"
        output_path = temp_path / "output_filled.pdf"

        content = await read_bounded_upload(pdf_file)
        require_pdf_signature(content)
        input_path.write_bytes(content)

        try:
            fill_report, mapping_result, fields_total, page_count = await asyncio.wait_for(
                asyncio.to_thread(
                    run_fill_pipeline,
                    input_path,
                    output_path,
                    parsed_user_data,
                    strict=strict,
                    allow_fallback_mapping=allow_fallback_mapping,
                    use_semantic_inference=use_semantic_inference,
                    max_pages=config.MAX_PDF_PAGES,
                    flatten=flatten,
                ),
                timeout=config.PDF_READ_TIMEOUT_SECONDS,
            )
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

        wants_json = _wants_json_fill_report(request)
        _audit_log_fill(
            request,
            fields_total=fields_total,
            report=fill_report,
            missing_required=len(mapping_result.missing_required),
            use_semantic_inference=use_semantic_inference,
            allow_fallback_mapping=allow_fallback_mapping,
            response_mode="json" if wants_json else "pdf",
        )

        if wants_json:
            pdf_bytes = output_path.read_bytes()
            decisions = [
                PreviewDecision(
                    field_name=d.field_name,
                    semantic_meaning=d.semantic_meaning,
                    selected_value=d.selected_value,
                    confidence=d.confidence,
                    reason=d.reason,
                    requires_review=d.requires_review,
                )
                for d in mapping_result.decisions
            ]
            payload = FillReportResponse(
                pages=page_count,
                field_count=fields_total,
                written_fields=list(fill_report.written_fields),
                skipped_review_fields=list(fill_report.skipped_review_fields),
                skipped_empty_fields=list(fill_report.skipped_empty_fields),
                skipped_unwritable_fields=list(fill_report.skipped_unwritable_fields),
                missing_required=list(mapping_result.missing_required),
                unmapped_user_keys=list(mapping_result.unmapped_user_keys),
                decisions=decisions,
                pdf_base64=base64.b64encode(pdf_bytes).decode("ascii"),
            )
            response_started = True
            return JSONResponse(
                content=payload.model_dump(),
                headers=_fill_report_headers(fill_report),
                background=BackgroundTask(temp_dir.cleanup),
            )

        response_started = True
        return FileResponse(
            path=output_path,
            media_type="application/pdf",
            filename=f"{Path(pdf_file.filename or 'filled').stem}_filled.pdf",
            headers=_fill_report_headers(fill_report),
            background=BackgroundTask(temp_dir.cleanup),
        )
    except UnresolvedRequiredFieldsError as exc:
        raise api_error(
            status_code=422,
            code="required_fields_unresolved",
            message="Required fields unresolved",
            details={
                "missing_fields": exc.missing_fields,
                "skipped_fields": exc.skipped_fields,
            },
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("PDF fill request failed")
        raise api_error(
            status_code=500,
            code="pdf_fill_failed",
            message="PDF fill failed",
        ) from exc
    finally:
        if temp_dir is not None and not response_started:
            temp_dir.cleanup()
        await pdf_file.close()
