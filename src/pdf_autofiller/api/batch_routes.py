"""Batch preview and fill HTTP route."""

from __future__ import annotations

import asyncio
import base64
import tempfile
from pathlib import Path
from typing import Literal, cast

from fastapi import APIRouter, File, Form, Request, UploadFile

from pdf_autofiller.errors import RecordsError
from pdf_autofiller.pipeline import fill_batch, preview_batch
from pdf_autofiller.records import MAX_RECORDS_BYTES, parse_records

from . import config
from .errors import ERROR_CATALOG, MUTATING_ERROR_CODES, api_error, openapi_error_responses
from .jobs import execute_pdf_job
from .request_parsing import parse_field_mapping
from .route_support import (
    _pdf_job_errors,
    _require_consistent_options,
    _save_pdf_upload,
    _unexpected_errors,
)
from .schemas import BatchItemResponse, BatchResponse
from .telemetry import emit_product_event

router = APIRouter()


@router.post(
    "/batch",
    response_model=BatchResponse,
    responses=openapi_error_responses(
        *MUTATING_ERROR_CODES,
        "invalid_records",
        "too_many_records",
        "batch_output_too_large",
        "user_data_too_deep",
        "invalid_field_mapping",
        "conflicting_options",
        "pdf_batch_failed",
    ),
)
async def batch_pdf(
    request: Request,
    pdf_file: UploadFile = File(...),
    records: str = Form(..., description="JSON array, JSONL, or CSV text"),
    records_format: str = Form("json", description="json, jsonl, or csv"),
    dry_run: bool = Form(False, description="Map every row and return the report without PDF bytes"),
    filename_key: str = Form("", description="Record field used as each PDF filename"),
    on_error: str = Form("continue", description="continue or stop"),
    strict: bool = Form(True),
    allow_fallback_mapping: bool = Form(False),
    use_semantic_inference: bool = Form(False),
    flatten: bool = Form(False),
    need_appearances: bool = Form(True),
    allow_partial: bool = Form(False),
    field_mapping: str = Form(
        "{}",
        description="JSON object mapping exact PDF field names to record keys",
    ),
) -> BatchResponse:
    """Fill one template for every record. One failed row does not hide the others."""
    del request
    temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-batch-")
    try:
        with _unexpected_errors("pdf_batch_failed"):
            if records_format not in {"json", "jsonl", "csv"}:
                raise api_error(
                    status_code=422,
                    code="invalid_records",
                    message="records_format must be json, jsonl, or csv",
                )
            if on_error not in {"continue", "stop"}:
                raise api_error(
                    status_code=422,
                    code="invalid_records",
                    message="on_error must be continue or stop",
                )
            if len(records.encode("utf-8")) > MAX_RECORDS_BYTES:
                raise api_error(
                    status_code=413,
                    code="payload_too_large",
                    message="Records exceed the 1 MiB batch text limit",
                )
            _require_consistent_options(strict=strict, allow_fallback_mapping=allow_fallback_mapping)
            parsed_field_mapping = parse_field_mapping(field_mapping)
            fmt = cast(Literal["json", "jsonl", "csv"], records_format)
            mode = cast(Literal["continue", "stop"], on_error)
            try:
                parsed = parse_records(records, fmt=fmt)
            except RecordsError as exc:
                status, message = ERROR_CATALOG[exc.code]
                raise api_error(status_code=status, code=exc.code, message=str(exc) or message) from exc
            input_path = await _save_pdf_upload(pdf_file, temp_dir)
            output_dir = Path(temp_dir.name) / "out"
            key = filename_key or None
            with _pdf_job_errors():
                if dry_run:
                    report = await asyncio.to_thread(
                        execute_pdf_job,
                        preview_batch,
                        input_path,
                        parsed,
                        timeout_seconds=config.PDF_READ_TIMEOUT_SECONDS,
                        on_error=mode,
                        strict=strict,
                        allow_fallback_mapping=allow_fallback_mapping,
                        use_semantic_inference=use_semantic_inference,
                        max_pages=config.MAX_PDF_PAGES,
                        allow_partial=allow_partial,
                        field_mapping=parsed_field_mapping,
                    )
                else:
                    report = await asyncio.to_thread(
                        execute_pdf_job,
                        fill_batch,
                        input_path,
                        parsed,
                        output_dir,
                        timeout_seconds=config.PDF_READ_TIMEOUT_SECONDS,
                        filename_key=key,
                        on_error=mode,
                        strict=strict,
                        allow_fallback_mapping=allow_fallback_mapping,
                        use_semantic_inference=use_semantic_inference,
                        max_pages=config.MAX_PDF_PAGES,
                        flatten=flatten,
                        need_appearances=need_appearances,
                        allow_partial=allow_partial,
                        field_mapping=parsed_field_mapping,
                        max_output_bytes=config.BATCH_MAX_RESPONSE_BYTES,
                    )
            items: list[BatchItemResponse] = []
            generated_bytes = sum(
                Path(item.output).stat().st_size for item in report.items if item.output and not dry_run
            )
            if generated_bytes > config.BATCH_MAX_RESPONSE_BYTES:
                raise api_error(
                    status_code=413,
                    code="batch_output_too_large",
                    message=ERROR_CATALOG["batch_output_too_large"][1],
                    details={
                        "generated_bytes": generated_bytes,
                        "max_response_bytes": config.BATCH_MAX_RESPONSE_BYTES,
                    },
                )
            for item in report.items:
                pdf_b64 = None
                filename = Path(item.output).name if item.output else None
                if item.output and not dry_run:
                    pdf_b64 = base64.b64encode(Path(item.output).read_bytes()).decode("ascii")
                items.append(
                    BatchItemResponse(
                        index=item.index,
                        filename=filename,
                        written_fields=list(item.written_fields),
                        missing_required_fields=list(item.missing_required_fields),
                        unfilled_fields=list(item.unfilled_fields),
                        error=item.error,
                        pdf_base64=pdf_b64,
                    )
                )
            response = BatchResponse(
                written=report.written,
                failed=report.failed,
                dry_run=dry_run,
                items=items,
            )
            emit_product_event(
                "batch_completed",
                records=len(parsed),
                written=response.written,
                failed=response.failed,
                dry_run=dry_run,
                ai_inference_enabled=use_semantic_inference,
                ai_fallback_enabled=allow_fallback_mapping,
            )
            return response
    finally:
        temp_dir.cleanup()
        await pdf_file.close()
