"""
HTTP boundary for the PDF autofill service.

This module owns request validation, authentication, and response contracts.
Core PDF logic remains in the reader/mapping/writer modules.

Security posture (this service accepts untrusted uploads from the public):
- Authentication on write endpoints is enabled by default and fails closed.
- Per-client rate limiting protects against request floods.
- Uploads are size-, signature-, and page-count-checked; the accompanying JSON
  is bounded in bytes, key count, and nesting depth.
- PDF parsing runs in a killable child process under a wall-clock timeout, so a
  hostile document cannot permanently consume a worker.
- Temporary files are removed on every code path.
- A structured, PII-free audit line is emitted per fill.
See docs/OPERATIONS.md for rationale and configuration.

Routes are served under ``/v1``. Unversioned paths remain as aliases so existing
callers keep working, but new consumers should use the versioned form.
"""

from __future__ import annotations

import logging
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import __version__
from .errors import PdfAutofillerError

# Re-exported for callers that have long imported it from this module. The
# redundant alias is the explicit re-export form, so linters keep it.
from .errors import UnresolvedRequiredFieldsError as UnresolvedRequiredFieldsError
from .http_support import (
    _api_error,
    _domain_error,
    _fill_report_headers,
    _guard,
    _parse_optional_json_object,
    _parse_user_data,
    _run_pipeline,
    _stage_upload,
    request_validation_payload,
)
from .mapping import alias_pack_status
from .models import FillReport, InspectReport
from .pipeline import enrich_fields, page_context_by_number, run_fill_pipeline, run_inspect_pipeline
from .playground import PLAYGROUND_HTML
from .semantics_cache import cache_stats
from .settings import get_settings
from .store import Profile, Template, profile_store, resolve_fill_inputs, template_store

logger = logging.getLogger(__name__)

UPLOAD_CHUNK_BYTES = 64 * 1024


def _configure_logger() -> None:
    level = getattr(logging, get_settings().log_level, logging.INFO)
    logger.setLevel(level if isinstance(level, int) else logging.INFO)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    checks: dict[str, str] = {}


class VersionResponse(BaseModel):
    service: str
    version: str


def _fallback_semantics(field):
    """Backward-compatible wrapper for tests importing the helper."""
    from .pipeline import fallback_semantics

    return fallback_semantics(field)


def _page_context_by_number(text_regions):
    """Backward-compatible wrapper for tests importing the helper."""
    return page_context_by_number(text_regions)


def _enrich_fields(fields, *, use_semantic_inference, page_context=None):
    """Backward-compatible wrapper for tests importing the helper."""
    return enrich_fields(
        fields, use_semantic_inference=use_semantic_inference, page_context=page_context
    )


def _audit_log_fill(
    request: Request,
    *,
    fields_total: int,
    report: FillReport,
    missing_required: int,
    use_semantic_inference: bool,
    allow_fallback_mapping: bool,
) -> None:
    """Emit a structured, PII-free audit record for a completed fill.

    This is the application-level audit trail. It deliberately records only
    counts, request identity, and which optional features ran — never field
    names or user values — so the line is safe to ship to a central log store.
    Persistent retention/storage is a deployment responsibility (see
    docs/OPERATIONS.md).
    """
    settings = get_settings()
    request_id = getattr(request.state, "request_id", "unknown")
    logger.info(
        "audit action=fill request_id=%s auth=%s fields_total=%d fields_written=%d "
        "fields_review_skipped=%d fields_empty_skipped=%d fields_invalid_skipped=%d "
        "missing_required=%d semantic_inference=%s fallback_mapping=%s flattened=%s",
        request_id,
        "enabled" if settings.auth_enabled else "disabled",
        fields_total,
        len(report.written_fields),
        len(report.skipped_review_fields),
        len(report.skipped_empty_fields),
        len(report.skipped_invalid_fields),
        missing_required,
        use_semantic_inference,
        allow_fallback_mapping,
        report.flattened,
    )



app = FastAPI(
    title="PDF Autofiller API",
    version=__version__,
    description=(
        "HTTP API for deterministic-first PDF form filling with optional semantic inference."
    ),
)

_cors_origins = get_settings().cors_allow_origins
if _cors_origins:
    # Opt-in only: a wildcard default would let any page on the internet drive a
    # deployment that a browser has already authenticated.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[
            "X-PDF-Fields-Written",
            "X-PDF-Fields-Skipped-Review",
            "X-PDF-Fields-Skipped-Empty",
            "X-PDF-Fields-Skipped-Invalid",
            "X-PDF-Flattened",
            "X-Request-ID",
        ],
    )


@app.exception_handler(RequestValidationError)
async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Normalize FastAPI request validation errors to API contract."""
    del request
    return JSONResponse(
        status_code=422,
        content={
            "detail": request_validation_payload(exc.errors())
        },
    )


@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    """Attach request ID, emit basic request logs, and time the handler."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed * 1000,
    )
    return response


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------

router = APIRouter()


@app.get("/")
def root() -> RedirectResponse:
    """Redirect browsers to the interactive playground."""
    return RedirectResponse(url="/playground")


@app.get("/playground", response_class=HTMLResponse)
def playground_page() -> HTMLResponse:
    """Serve the browser playground for trying fills without curl."""
    return HTMLResponse(content=PLAYGROUND_HTML)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    if not settings.auth_enabled:
        auth_state = "disabled"
    elif settings.auth_configured():
        auth_state = "enabled"
    else:
        auth_state = "misconfigured"

    checks = {
        "auth": auth_state,
        "semantics_cache_entries": str(cache_stats()["entries"]),
        **alias_pack_status(),
    }
    return HealthResponse(
        status="ok" if auth_state != "misconfigured" else "degraded",
        service="pdf-autofiller",
        version=__version__,
        checks=checks,
    )


@router.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(service="pdf-autofiller", version=__version__)


@router.post("/inspect", response_model=InspectReport)
async def inspect(
    request: Request,
    pdf_file: UploadFile = File(...),
    user_data: str = Form("{}"),
    strict: bool = Form(True),
    allow_fallback_mapping: bool = Form(False),
    use_semantic_inference: bool = Form(False),
    overrides: str = Form(""),
    template: str = Form(""),
    profile: str = Form(""),
) -> InspectReport:
    """
    Report a form's fields and preview what a fill would do. Writes nothing.

    This is the answer to "what keys does this PDF want?", which previously
    could only be discovered by attempting a fill and reading the error.
    """
    settings = get_settings()
    temp_dir = None
    try:
        _guard(request)
        parsed_user_data = _parse_user_data(user_data, settings)
        request_overrides = _parse_optional_json_object(overrides, "overrides")

        resolved_data, resolved_overrides, _ = resolve_fill_inputs(
            template_name=template or None,
            profile_name=profile or None,
            user_data=parsed_user_data,
            overrides=request_overrides,
        )

        temp_dir, input_path = await _stage_upload(pdf_file, settings)
        report: InspectReport = await _run_pipeline(
            run_inspect_pipeline,
            input_path,
            resolved_data,
            strict=strict,
            allow_fallback_mapping=allow_fallback_mapping,
            use_semantic_inference=use_semantic_inference,
            max_pages=settings.max_pdf_pages,
            max_text_chars=settings.max_pdf_text_chars,
            overrides=resolved_overrides,
        )
        return report
    except HTTPException:
        raise
    except PdfAutofillerError as exc:
        raise _domain_error(exc) from exc
    except Exception as exc:
        logger.exception("PDF inspect request failed")
        raise _api_error(
            status_code=500, code="pdf_inspect_failed", message="PDF inspect failed"
        ) from exc
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
        await pdf_file.close()


@router.post("/fill")
async def fill(
    request: Request,
    pdf_file: UploadFile = File(...),
    user_data: str = Form("{}"),
    strict: bool = Form(True),
    allow_fallback_mapping: bool = Form(False),
    use_semantic_inference: bool = Form(False),
    flatten: bool = Form(False),
    allow_key_reuse: bool = Form(True),
    overrides: str = Form(""),
    template: str = Form(""),
    profile: str = Form(""),
    response_format: str = Form("pdf"),
):
    """
    Fill a PDF form from uploaded file and user data.

    Args:
        pdf_file: Uploaded PDF file
        user_data: JSON object encoded as form text
        strict: Disable fallback mapping when true
        allow_fallback_mapping: Enable fallback mapping for unmapped high-value fields
        use_semantic_inference: Enable semantic inference before mapping
        flatten: Remove the interactive form so the result cannot be edited
        allow_key_reuse: Permit one user key to fill several matching fields
        overrides: JSON object of explicit field_name -> value assignments
        template: Name of a stored template to apply
        profile: Name of a stored profile to use as base data
        response_format: "pdf" for the raw document, "json" for the document
            plus the full fill report
    """
    settings = get_settings()
    temp_dir = None
    # The FileResponse streams the output and cleans up the temp dir via a
    # BackgroundTask. On every other path we must clean up here, so track whether
    # ownership of the temp dir was handed off to a successful response.
    response_started = False

    try:
        _guard(request)
        parsed_user_data = _parse_user_data(user_data, settings)
        request_overrides = _parse_optional_json_object(overrides, "overrides")

        resolved_data, resolved_overrides, stored_template = resolve_fill_inputs(
            template_name=template or None,
            profile_name=profile or None,
            user_data=parsed_user_data,
            overrides=request_overrides,
        )
        # A fill needs values from somewhere. user_data is optional now that a
        # profile or template can supply them, but all three being empty means
        # the caller forgot something — better to say so than to hand back an
        # unchanged document that looks like it worked.
        if not resolved_data and not resolved_overrides:
            raise _api_error(
                status_code=422,
                code="no_fill_data",
                message=(
                    "No data to fill. Supply user_data, a profile, or overrides."
                ),
            )
        if stored_template is not None:
            flatten = flatten or stored_template.flatten

        temp_dir, input_path = await _stage_upload(pdf_file, settings)
        output_path = Path(temp_dir.name) / "output_filled.pdf"

        fill_report, mapping_result, fields_total = await _run_pipeline(
            run_fill_pipeline,
            input_path,
            output_path,
            resolved_data,
            strict=strict,
            allow_fallback_mapping=allow_fallback_mapping,
            use_semantic_inference=use_semantic_inference,
            max_pages=settings.max_pdf_pages,
            max_text_chars=settings.max_pdf_text_chars,
            overrides=resolved_overrides,
            allow_key_reuse=allow_key_reuse,
            flatten=flatten,
        )

        _audit_log_fill(
            request,
            fields_total=fields_total,
            report=fill_report,
            missing_required=len(mapping_result.missing_required),
            use_semantic_inference=use_semantic_inference,
            allow_fallback_mapping=allow_fallback_mapping,
        )

        wants_json = response_format.lower() == "json" or "application/json" in (
            request.headers.get("Accept", "")
        )
        if wants_json:
            import base64

            payload = {
                "report": fill_report.model_dump(),
                "mapping": mapping_result.model_dump(),
                "fields_total": fields_total,
                "pdf_base64": base64.b64encode(output_path.read_bytes()).decode("ascii"),
                "filename": f"{Path(pdf_file.filename or 'filled').stem}_filled.pdf",
            }
            return JSONResponse(content=payload, headers=_fill_report_headers(fill_report))

        response = FileResponse(
            path=output_path,
            media_type="application/pdf",
            filename=f"{Path(pdf_file.filename or 'filled').stem}_filled.pdf",
            headers=_fill_report_headers(fill_report),
            background=BackgroundTask(temp_dir.cleanup),
        )
        response_started = True
        return response
    except HTTPException:
        raise
    except PdfAutofillerError as exc:
        raise _domain_error(exc) from exc
    except Exception as exc:
        logger.exception("PDF fill request failed")
        raise _api_error(
            status_code=500, code="pdf_fill_failed", message="PDF fill failed"
        ) from exc
    finally:
        # Clean up unless a successful response took ownership of the temp dir.
        if temp_dir is not None and not response_started:
            temp_dir.cleanup()
        await pdf_file.close()


# --- templates and profiles ------------------------------------------------


@router.get("/templates")
def list_templates(request: Request) -> dict[str, Any]:
    """List stored form templates."""
    _guard(request)
    return {"templates": [t.model_dump() for t in template_store().list()]}


@router.put("/templates/{name}")
def put_template(request: Request, name: str, template: Template) -> dict[str, Any]:
    """Create or replace a stored template."""
    _guard(request)
    template.name = name
    saved: Template = template_store().save(template)
    return dict(saved.model_dump())


@router.get("/templates/{name}")
def get_template(request: Request, name: str) -> dict[str, Any]:
    """Fetch one stored template."""
    _guard(request)
    try:
        loaded: Template = template_store().get(name)
    except PdfAutofillerError as exc:
        raise _domain_error(exc) from exc
    return dict(loaded.model_dump())


@router.delete("/templates/{name}")
def delete_template(request: Request, name: str) -> dict[str, str]:
    """Delete a stored template."""
    _guard(request)
    try:
        template_store().delete(name)
    except PdfAutofillerError as exc:
        raise _domain_error(exc) from exc
    return {"deleted": name}


@router.get("/profiles")
def list_profiles(request: Request) -> dict[str, Any]:
    """List stored profiles, without their data.

    Profiles hold personal information, so the index returns names and
    descriptions only; the full payload requires asking for it by name.
    """
    _guard(request)
    return {
        "profiles": [
            {"name": p.name, "description": p.description, "keys": sorted(p.data)}
            for p in profile_store().list()
        ]
    }


@router.put("/profiles/{name}")
def put_profile(request: Request, name: str, profile: Profile) -> dict[str, Any]:
    """Create or replace a stored profile."""
    _guard(request)
    profile.name = name
    saved: Profile = profile_store().save(profile)
    return {"name": saved.name, "description": saved.description, "keys": sorted(saved.data)}


@router.get("/profiles/{name}")
def get_profile(request: Request, name: str) -> dict[str, Any]:
    """Fetch one stored profile, including its data."""
    _guard(request)
    try:
        loaded: Profile = profile_store().get(name)
    except PdfAutofillerError as exc:
        raise _domain_error(exc) from exc
    return dict(loaded.model_dump())


@router.delete("/profiles/{name}")
def delete_profile(request: Request, name: str) -> dict[str, str]:
    """Delete a stored profile."""
    _guard(request)
    try:
        profile_store().delete(name)
    except PdfAutofillerError as exc:
        raise _domain_error(exc) from exc
    return {"deleted": name}


# Versioned routes are canonical; the unversioned aliases keep existing callers
# working through the transition.
app.include_router(router, prefix="/v1", tags=["v1"])
app.include_router(router, include_in_schema=False)


def run() -> None:
    """Run local API server."""
    import uvicorn

    _configure_logger()
    level = getattr(logging, get_settings().log_level, logging.INFO)
    if not logging.getLogger().handlers:
        logging.basicConfig(level=level)
    uvicorn.run(
        "pdf_autofiller.api_service:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level=logging.getLevelName(level).lower(),
    )
