"""HTTP route handlers."""

from __future__ import annotations

import asyncio
import base64
import logging
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.background import BackgroundTask

from pdf_autofiller.field_utils import is_opaque_field_name
from pdf_autofiller.models import FillTemplate
from pdf_autofiller.pipeline import (
    fill_template,
    run_fill_pipeline,
    run_preview_pipeline,
)
from pdf_autofiller.pipeline import (
    inspect as inspect_local,
)

from . import config
from .batch_routes import router as batch_router
from .errors import (
    MUTATING_ERROR_CODES,
    openapi_error_responses,
)
from .jobs import execute_pdf_job
from .request_parsing import parse_field_mapping, parse_user_data
from .route_support import (
    _audit_log_fill,
    _fill_report_headers,
    _pdf_job_errors,
    _require_consistent_options,
    _save_pdf_upload,
    _unexpected_errors,
    _wants_json_fill_report,
)
from .schemas import (
    FillReportResponse,
    InspectField,
    InspectResponse,
    PreviewDecision,
    PreviewResponse,
)
from .system_routes import router as system_router
from .telemetry import emit_product_event
from .template_routes import router as template_workspace_router

logger = logging.getLogger(__name__)

router = APIRouter()
router.include_router(system_router)
router.include_router(batch_router)
router.include_router(template_workspace_router)


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
    temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-inspect-")
    try:
        with _unexpected_errors("pdf_inspect_failed"):
            input_path = await _save_pdf_upload(pdf_file, temp_dir)
            with _pdf_job_errors():
                inventory = await asyncio.to_thread(
                    execute_pdf_job,
                    inspect_local,
                    input_path,
                    timeout_seconds=config.PDF_READ_TIMEOUT_SECONDS,
                    max_pages=config.MAX_PDF_PAGES,
                )
            fields = [
                InspectField(
                    name=field.name,
                    field_type=field.field_type,
                    required=field.required,
                    page_number=field.page_number,
                    current_value=field.value,
                    name_quality=("opaque" if is_opaque_field_name(field.name) else "readable"),
                )
                for field in inventory.fields
            ]
            response = InspectResponse(
                pages=inventory.pages,
                field_count=inventory.field_count,
                fields=fields,
                opaque_field_count=inventory.opaque_field_count,
                opaque_fields=list(inventory.opaque_fields),
                mapping_hints=list(inventory.mapping_hints),
            )
            emit_product_event(
                "inspect_completed",
                fields_total=response.field_count,
                opaque_fields=response.opaque_field_count,
            )
            return response
    finally:
        temp_dir.cleanup()
        await pdf_file.close()


@router.post(
    "/template",
    response_model=FillTemplate,
    responses=openapi_error_responses(*MUTATING_ERROR_CODES, "pdf_template_failed"),
)
async def template_pdf(pdf_file: UploadFile = File(...)) -> FillTemplate:
    """Generate starter JSON and an editable exact mapping for an uploaded PDF."""
    temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-template-")
    try:
        with _unexpected_errors("pdf_template_failed"):
            input_path = await _save_pdf_upload(pdf_file, temp_dir)
            with _pdf_job_errors():
                template = await asyncio.to_thread(
                    execute_pdf_job,
                    fill_template,
                    input_path,
                    timeout_seconds=config.PDF_READ_TIMEOUT_SECONDS,
                    max_pages=config.MAX_PDF_PAGES,
                )
            emit_product_event(
                "template_completed",
                fields_total=len(template.fields),
                required_fields=len(template.required_keys),
            )
            return template
    finally:
        temp_dir.cleanup()
        await pdf_file.close()


@router.post(
    "/preview",
    response_model=PreviewResponse,
    responses=openapi_error_responses(
        *MUTATING_ERROR_CODES,
        "invalid_user_data_json",
        "invalid_user_data_type",
        "user_data_too_deep",
        "invalid_field_mapping",
        "conflicting_options",
        "pdf_preview_failed",
    ),
)
async def preview_pdf(
    request: Request,
    pdf_file: UploadFile = File(...),
    user_data: str = Form(...),
    strict: bool = Form(
        True,
        description=(
            "When true, disables the AI key fallback only. Required fields are still enforced on /fill."
        ),
    ),
    allow_fallback_mapping: bool = Form(False),
    use_semantic_inference: bool = Form(False),
    field_mapping: str = Form(
        "{}",
        description="JSON object mapping exact PDF field names to user_data keys",
    ),
) -> PreviewResponse:
    """Return mapping decisions without writing a PDF (inspect → map debug loop)."""
    temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-preview-")
    try:
        with _unexpected_errors("pdf_preview_failed"):
            _require_consistent_options(strict=strict, allow_fallback_mapping=allow_fallback_mapping)
            parsed_user_data = parse_user_data(user_data)
            parsed_field_mapping = parse_field_mapping(field_mapping)
            input_path = await _save_pdf_upload(pdf_file, temp_dir)
            with _pdf_job_errors():
                mapping_result, field_count, page_count = await asyncio.to_thread(
                    execute_pdf_job,
                    run_preview_pipeline,
                    input_path,
                    parsed_user_data,
                    timeout_seconds=config.PDF_READ_TIMEOUT_SECONDS,
                    strict=strict,
                    allow_fallback_mapping=allow_fallback_mapping,
                    use_semantic_inference=use_semantic_inference,
                    max_pages=config.MAX_PDF_PAGES,
                    field_mapping=parsed_field_mapping,
                )
            response = PreviewResponse(
                pages=page_count,
                field_count=field_count,
                decisions=[PreviewDecision(**d.model_dump()) for d in mapping_result.decisions],
                missing_required=list(mapping_result.missing_required),
                unmapped_user_keys=list(mapping_result.unmapped_user_keys),
                mapping_hints=list(mapping_result.mapping_hints),
            )
            emit_product_event(
                "preview_completed",
                fields_total=response.field_count,
                decisions=len(response.decisions),
                missing_required=len(response.missing_required),
                unmapped_keys=len(response.unmapped_user_keys),
                ai_inference_enabled=use_semantic_inference,
                ai_fallback_enabled=allow_fallback_mapping,
            )
            return response
    finally:
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
                        "Fill report JSON including base64 PDF when Accept prefers application/json"
                    ),
                    "schema": FillReportResponse.model_json_schema(),
                },
            },
        },
        **openapi_error_responses(
            *MUTATING_ERROR_CODES,
            "invalid_user_data_json",
            "invalid_user_data_type",
            "user_data_too_deep",
            "invalid_field_mapping",
            "conflicting_options",
            "required_fields_unresolved",
            "pdf_fill_failed",
        ),
    },
)
async def fill(
    request: Request,
    pdf_file: UploadFile = File(...),
    user_data: str = Form(...),
    strict: bool = Form(
        True,
        description=(
            "When true, disables the AI key fallback only. "
            "Required fields are still enforced before a PDF is returned."
        ),
    ),
    allow_fallback_mapping: bool = Form(False),
    use_semantic_inference: bool = Form(False),
    flatten: bool = Form(False),
    need_appearances: bool = Form(
        True,
        description=(
            "When true (default), set AcroForm /NeedAppearances so viewers "
            "regenerate visible field appearances from written values."
        ),
    ),
    allow_partial: bool = Form(
        False,
        description=(
            "When true, return the PDF even if required fields are unresolved; "
            "they are listed in missing_required_fields / X-PDF-Fields-Missing-Required."
        ),
    ),
    field_mapping: str = Form(
        "{}",
        description="JSON object mapping exact PDF field names to user_data keys",
    ),
) -> Response:
    """Fill a PDF form from uploaded file and user data."""
    temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-")
    response_started = False  # once a response owns temp_dir, it cleans it up afterwards
    try:
        with _unexpected_errors("pdf_fill_failed"):
            _require_consistent_options(strict=strict, allow_fallback_mapping=allow_fallback_mapping)
            parsed_user_data = parse_user_data(user_data)
            parsed_field_mapping = parse_field_mapping(field_mapping)
            input_path = await _save_pdf_upload(pdf_file, temp_dir)
            output_path = input_path.with_name("output_filled.pdf")

            with _pdf_job_errors():
                fill_report, mapping_result, fields_total, page_count = await asyncio.to_thread(
                    execute_pdf_job,
                    run_fill_pipeline,
                    input_path,
                    output_path,
                    parsed_user_data,
                    timeout_seconds=config.PDF_READ_TIMEOUT_SECONDS,
                    strict=strict,
                    allow_fallback_mapping=allow_fallback_mapping,
                    use_semantic_inference=use_semantic_inference,
                    max_pages=config.MAX_PDF_PAGES,
                    flatten=flatten,
                    need_appearances=need_appearances,
                    allow_partial=allow_partial,
                    field_mapping=parsed_field_mapping,
                )

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
            emit_product_event(
                "fill_completed",
                fields_total=fields_total,
                written=len(fill_report.written_fields),
                missing_required=len(mapping_result.missing_required),
                ai_inference_enabled=use_semantic_inference,
                ai_fallback_enabled=allow_fallback_mapping,
            )

            if wants_json:
                pdf_bytes = output_path.read_bytes()
                decisions = [PreviewDecision(**d.model_dump()) for d in mapping_result.decisions]
                payload = FillReportResponse(
                    pages=page_count,
                    field_count=fields_total,
                    written_fields=list(fill_report.written_fields),
                    skipped_review_fields=list(fill_report.skipped_review_fields),
                    skipped_empty_fields=list(fill_report.skipped_empty_fields),
                    skipped_unwritable_fields=list(fill_report.skipped_unwritable_fields),
                    display_warnings=list(fill_report.display_warnings),
                    ai_assisted_fields=list(fill_report.ai_assisted_fields),
                    missing_required=list(mapping_result.missing_required),
                    missing_required_fields=list(fill_report.missing_required_fields),
                    unfilled_fields=list(fill_report.unfilled_fields),
                    unmapped_user_keys=list(mapping_result.unmapped_user_keys),
                    decisions=decisions,
                    mapping_hints=list(mapping_result.mapping_hints),
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
    finally:
        if not response_started:
            temp_dir.cleanup()
        await pdf_file.close()
