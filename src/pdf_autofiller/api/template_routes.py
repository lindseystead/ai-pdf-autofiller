"""Durable, versioned template and fill-job API."""

from __future__ import annotations

import asyncio
import logging
import tempfile
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from pdf_autofiller.models import FillTemplate
from pdf_autofiller.pipeline import fill_template, run_fill_pipeline
from pdf_autofiller.template_store import (
    JobNotFoundError,
    StoredJob,
    StoredTemplateVersion,
    TemplateConflictError,
    TemplateNotFoundError,
    TemplateStateError,
    TemplateStore,
)
from pdf_autofiller.user_data import flatten_user_data

from . import config
from .errors import api_error
from .jobs import execute_pdf_job
from .request_parsing import parse_field_mapping
from .route_support import _pdf_job_errors, _save_pdf_upload, _unexpected_errors
from .security import guard_api_request

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["template workspace"])


class TemplateVersionResponse(BaseModel):
    id: str
    name: str
    version: int
    revision: int
    status: Literal["draft", "published"]
    source_sha256: str
    starter_data: dict[str, str | bool]
    required_keys: list[str]
    fields: list[dict[str, Any]]
    mapping: dict[str, str]
    source_url: str
    created_at: str
    published_at: str | None = None


class MappingUpdateRequest(BaseModel):
    expected_revision: int = Field(ge=1)
    mapping: dict[str, str]


class PublishRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class StoredFillRequest(BaseModel):
    data: dict[str, Any]
    flatten: bool = False
    need_appearances: bool = True
    allow_partial: bool = False


class FillJobResponse(BaseModel):
    id: str
    template_id: str
    template_version: int
    status: Literal["running", "completed", "failed"]
    report: dict[str, Any] | None = None
    error_code: str | None = None
    artifact_url: str | None = None
    created_at: str
    completed_at: str | None = None


class CorrectionResponse(BaseModel):
    id: str
    template_id: str
    template_version: int
    field_name: str
    suggested_key: str | None = None
    approved_key: str | None = None
    created_at: str


@lru_cache(maxsize=8)
def _store_for_root(root: str) -> TemplateStore:
    return TemplateStore(Path(root))


def _store() -> TemplateStore:
    return _store_for_root(str(config.PRODUCT_DATA_DIR.resolve()))


def _template_response(value: StoredTemplateVersion) -> TemplateVersionResponse:
    template = value.template
    return TemplateVersionResponse(
        id=value.template_id,
        name=value.name,
        version=value.version,
        revision=value.revision,
        status=value.status,
        source_sha256=value.source_sha256,
        starter_data=template.get("example", {}),
        required_keys=template.get("required_keys", []),
        fields=template.get("fields", []),
        mapping=value.mapping,
        source_url=f"/v1/templates/{value.template_id}/source?version={value.version}",
        created_at=value.created_at,
        published_at=value.published_at,
    )


def _job_response(value: StoredJob) -> FillJobResponse:
    return FillJobResponse(
        id=value.id,
        template_id=value.template_id,
        template_version=value.template_version,
        status=value.status,
        report=value.report,
        error_code=value.error_code,
        artifact_url=f"/v1/jobs/{value.id}/artifact" if value.artifact_key else None,
        created_at=value.created_at,
        completed_at=value.completed_at,
    )


async def _analyze_upload(
    pdf_file: UploadFile, temp_dir: tempfile.TemporaryDirectory
) -> tuple[FillTemplate, bytes]:
    input_path = await _save_pdf_upload(pdf_file, temp_dir)
    with _pdf_job_errors():
        generated: FillTemplate = await asyncio.to_thread(
            execute_pdf_job,
            fill_template,
            input_path,
            timeout_seconds=config.PDF_READ_TIMEOUT_SECONDS,
            max_pages=config.MAX_PDF_PAGES,
        )
    return generated, input_path.read_bytes()


def _starter_mapping(generated: FillTemplate) -> dict[str, str]:
    return {field.field_name: field.key for field in generated.fields if field.key is not None}


def _translate_store_error(exc: Exception) -> HTTPException:
    if isinstance(exc, TemplateNotFoundError):
        return api_error(status_code=404, code="template_not_found", message="Template not found")
    if isinstance(exc, JobNotFoundError):
        return api_error(status_code=404, code="fill_job_not_found", message="Fill job not found")
    if isinstance(exc, TemplateConflictError):
        return api_error(
            status_code=409,
            code="template_revision_conflict",
            message="Template draft changed; reload and try again",
        )
    if isinstance(exc, TemplateStateError):
        if "already published" in str(exc):
            code = "template_already_published"
            message = "Template version is already published"
        elif "current draft" in str(exc):
            code = "template_draft_exists"
            message = "Finish or publish the current draft first"
        else:
            code = "template_not_published"
            message = str(exc)
        return api_error(status_code=409, code=code, message=message)
    logger.exception("Template store failure", exc_info=exc)
    return api_error(status_code=500, code="template_store_failed", message="Template store operation failed")


def _validate_mapping(
    template: dict[str, Any],
    mapping: dict[str, str],
    *,
    require_required_fields: bool,
) -> None:
    valid_entries = all(
        isinstance(field, str) and field and isinstance(key, str) and key for field, key in mapping.items()
    )
    if not valid_entries:
        raise api_error(
            status_code=422,
            code="invalid_template_mapping",
            message="Template mapping keys and values must be non-empty strings",
        )
    fields = template.get("fields", [])
    known: set[str] = set()
    signature_fields: set[str] = set()
    required_fields: set[str] = set()
    for field in fields:
        if not isinstance(field, dict):
            continue
        field_name = field.get("field_name")
        if not isinstance(field_name, str):
            continue
        known.add(field_name)
        if field.get("field_type") == "signature":
            signature_fields.add(field_name)
        elif field.get("required") is True:
            required_fields.add(field_name)
    unknown = sorted(set(mapping) - known)
    if unknown:
        raise api_error(
            status_code=422,
            code="invalid_template_mapping",
            message="Template mapping references unknown PDF fields",
            details={"unknown_fields": unknown},
        )
    mapped_signatures = sorted(set(mapping) & signature_fields)
    if mapped_signatures:
        raise api_error(
            status_code=422,
            code="invalid_template_mapping",
            message="Signature fields cannot be mapped",
            details={"signature_fields": mapped_signatures},
        )
    missing = sorted(required_fields - set(mapping))
    if require_required_fields and missing:
        raise api_error(
            status_code=422,
            code="invalid_template_mapping",
            message="Every required PDF field must be mapped before publishing",
            details={"missing_required_fields": missing},
        )


@router.post("/templates", response_model=TemplateVersionResponse, status_code=201)
async def create_stored_template(
    request: Request,
    pdf_file: UploadFile = File(...),
    name: str = Form(..., min_length=1, max_length=120),
    field_mapping: str = Form("{}"),
) -> TemplateVersionResponse:
    """Upload one PDF and create a durable mapping draft."""
    del request  # guarded by UploadGuardMiddleware before multipart parsing
    temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-stored-template-")
    try:
        with _unexpected_errors("template_store_failed"):
            generated, content = await _analyze_upload(pdf_file, temp_dir)
            clean_name = name.strip()
            if not clean_name:
                raise api_error(
                    status_code=422,
                    code="request_validation_error",
                    message="Template name cannot be blank",
                )
            store = _store()
            source_key, digest = store.objects.put_source(content)
            template_payload = generated.model_dump(mode="json")
            supplied_mapping = parse_field_mapping(field_mapping)
            mapping = supplied_mapping or _starter_mapping(generated)
            _validate_mapping(
                template_payload,
                mapping,
                require_required_fields=False,
            )
            stored = store.repository.create_template(
                name=clean_name,
                source_sha256=digest,
                source_key=source_key,
                template=template_payload,
                mapping=mapping,
            )
            return _template_response(stored)
    finally:
        temp_dir.cleanup()
        await pdf_file.close()


@router.post("/templates/{template_id}/versions", response_model=TemplateVersionResponse, status_code=201)
async def create_template_version(
    template_id: str,
    request: Request,
    pdf_file: UploadFile = File(...),
) -> TemplateVersionResponse:
    """Upload a replacement PDF as a new immutable-version draft."""
    del request  # guarded by UploadGuardMiddleware before multipart parsing
    temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-template-version-")
    try:
        with _unexpected_errors("template_store_failed"):
            generated, content = await _analyze_upload(pdf_file, temp_dir)
            store = _store()
            source_key, digest = store.objects.put_source(content)
            try:
                stored = store.repository.create_version(
                    template_id,
                    source_sha256=digest,
                    source_key=source_key,
                    template=generated.model_dump(mode="json"),
                    mapping=_starter_mapping(generated),
                )
            except Exception as exc:
                raise _translate_store_error(exc) from exc
            return _template_response(stored)
    finally:
        temp_dir.cleanup()
        await pdf_file.close()


@router.get("/templates", response_model=list[TemplateVersionResponse])
def list_stored_templates(request: Request) -> list[TemplateVersionResponse]:
    guard_api_request(request)
    try:
        return [_template_response(item) for item in _store().repository.list_templates()]
    except Exception as exc:
        raise _translate_store_error(exc) from exc


@router.get("/templates/{template_id}", response_model=TemplateVersionResponse)
def get_stored_template(template_id: str, request: Request) -> TemplateVersionResponse:
    guard_api_request(request)
    try:
        return _template_response(_store().repository.get_latest(template_id))
    except Exception as exc:
        raise _translate_store_error(exc) from exc


@router.get("/templates/{template_id}/corrections", response_model=list[CorrectionResponse])
def list_template_corrections(template_id: str, request: Request) -> list[CorrectionResponse]:
    """Return value-free mapping corrections for evaluation and alias review."""
    guard_api_request(request)
    try:
        corrections = _store().repository.list_corrections(template_id)
        return [CorrectionResponse(**item.model_dump()) for item in corrections]
    except Exception as exc:
        raise _translate_store_error(exc) from exc


@router.get("/templates/{template_id}/source")
def get_template_source(template_id: str, request: Request, version: int | None = None) -> FileResponse:
    guard_api_request(request)
    try:
        store = _store()
        stored = (
            store.repository.get_version(template_id, version)
            if version is not None
            else store.repository.get_latest(template_id)
        )
        path = store.objects.resolve(stored.source_key)
        if not path.is_file():
            raise OSError("Stored source object is missing")
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=f"template-v{stored.version}.pdf",
        )
    except Exception as exc:
        raise _translate_store_error(exc) from exc


@router.put("/templates/{template_id}/mapping", response_model=TemplateVersionResponse)
def update_template_mapping(
    template_id: str,
    payload: MappingUpdateRequest,
    request: Request,
) -> TemplateVersionResponse:
    guard_api_request(request)
    try:
        repository = _store().repository
        current = repository.get_latest(template_id)
        _validate_mapping(
            current.template,
            payload.mapping,
            require_required_fields=False,
        )
        return _template_response(
            repository.update_mapping(
                template_id,
                mapping=payload.mapping,
                expected_revision=payload.expected_revision,
            )
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_store_error(exc) from exc


@router.post("/templates/{template_id}/publish", response_model=TemplateVersionResponse)
def publish_template(
    template_id: str,
    payload: PublishRequest,
    request: Request,
) -> TemplateVersionResponse:
    guard_api_request(request)
    try:
        repository = _store().repository
        current = repository.get_latest(template_id)
        _validate_mapping(
            current.template,
            current.mapping,
            require_required_fields=True,
        )
        published = repository.publish(template_id, expected_revision=payload.expected_revision)
        return _template_response(published)
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_store_error(exc) from exc


def _api_error_code(exc: HTTPException) -> str:
    detail = exc.detail
    if isinstance(detail, dict):
        error = detail.get("error")
        if isinstance(error, dict) and isinstance(error.get("code"), str):
            return error["code"]
    return "pdf_fill_failed"


@router.post("/templates/{template_id}/fills", response_model=FillJobResponse, status_code=201)
async def fill_stored_template(
    template_id: str,
    payload: StoredFillRequest,
    request: Request,
) -> FillJobResponse:
    guard_api_request(request)
    try:
        store = _store()
        template = store.repository.get_published(template_id)
    except Exception as exc:
        raise _translate_store_error(exc) from exc

    job = store.repository.create_job(template_id, template.version)
    temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-stored-fill-")
    try:
        source = store.objects.resolve(template.source_key)
        output = Path(temp_dir.name) / "output.pdf"
        # A published mapping is a schema: optional keys may be absent from an
        # individual record. Add explicit empty values so the core can honor the
        # exact mapping without falling back to heuristics; required empties are
        # still rejected by the pipeline unless allow_partial is selected.
        fill_data = dict(payload.data)
        present_keys = flatten_user_data(payload.data).candidates()
        for mapped_key in template.mapping.values():
            if mapped_key not in present_keys:
                fill_data[mapped_key] = None
        try:
            with _pdf_job_errors():
                fill_report, _mapping, _field_count, _pages = await asyncio.to_thread(
                    execute_pdf_job,
                    run_fill_pipeline,
                    source,
                    output,
                    fill_data,
                    timeout_seconds=config.PDF_READ_TIMEOUT_SECONDS,
                    strict=True,
                    allow_fallback_mapping=False,
                    use_semantic_inference=False,
                    max_pages=config.MAX_PDF_PAGES,
                    flatten=payload.flatten,
                    need_appearances=payload.need_appearances,
                    allow_partial=payload.allow_partial,
                    field_mapping=template.mapping,
                )
        except HTTPException as exc:
            store.repository.fail_job(job.id, error_code=_api_error_code(exc))
            raise
        artifact_key = store.objects.put_artifact(job.id, output.read_bytes())
        completed = store.repository.complete_job(
            job.id,
            report=fill_report.model_dump(mode="json"),
            artifact_key=artifact_key,
        )
        return _job_response(completed)
    except HTTPException:
        raise
    except Exception as exc:
        with suppress(JobNotFoundError):
            store.repository.fail_job(job.id, error_code="pdf_fill_failed")
        logger.exception("Stored template fill failed")
        raise api_error(status_code=500, code="pdf_fill_failed", message="PDF fill failed") from exc
    finally:
        temp_dir.cleanup()


@router.get("/jobs/{job_id}", response_model=FillJobResponse)
def get_fill_job(job_id: str, request: Request) -> FillJobResponse:
    guard_api_request(request)
    try:
        return _job_response(_store().repository.get_job(job_id))
    except Exception as exc:
        raise _translate_store_error(exc) from exc


@router.get("/jobs/{job_id}/artifact")
def get_fill_artifact(job_id: str, request: Request) -> FileResponse:
    guard_api_request(request)
    try:
        store = _store()
        job = store.repository.get_job(job_id)
        if job.status != "completed" or not job.artifact_key:
            raise api_error(
                status_code=409,
                code="fill_job_not_completed",
                message="Fill job has no completed artifact",
            )
        path = store.objects.resolve(job.artifact_key)
        if not path.is_file():
            raise OSError("Stored artifact is missing")
        return FileResponse(path, media_type="application/pdf", filename=f"{job.id}.pdf")
    except HTTPException:
        raise
    except Exception as exc:
        raise _translate_store_error(exc) from exc
