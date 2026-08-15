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

import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from pydantic import BaseModel
from starlette.background import BackgroundTask

from . import metrics
from . import __version__
from .errors import (
    PdfAutofillerError,
    UserDataTooLargeError,
)

# Re-exported for callers that have long imported it from this module. The
# redundant alias is the explicit re-export form, so linters keep it.
from .errors import UnresolvedRequiredFieldsError as UnresolvedRequiredFieldsError
from .execution import run_isolated
from .mapping import alias_pack_status
from .models import FillReport, InspectReport
from .pipeline import enrich_fields, page_context_by_number, run_fill_pipeline, run_inspect_pipeline
from .playground import PLAYGROUND_HTML
from .semantics_cache import cache_stats
from .settings import Settings, get_settings
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


def _api_error_payload(
    *, code: str, message: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Build a consistent API error payload."""
    payload: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details:
        payload["error"]["details"] = details
    return payload


def _api_error(
    *, status_code: int, code: str, message: str, details: dict[str, Any] | None = None
) -> HTTPException:
    # Centralize API error formatting so clients can rely on one contract
    # regardless of which endpoint raised the error.
    """Build a consistent API exception payload."""
    return HTTPException(
        status_code=status_code,
        detail=_api_error_payload(code=code, message=message, details=details),
    )


def _domain_error(exc: PdfAutofillerError) -> HTTPException:
    """Translate a typed pipeline error into its HTTP response.

    Every domain error carries its own code and status, so adding an error to
    :mod:`pdf_autofiller.errors` surfaces it here with no change at this layer.
    """
    return _api_error(
        status_code=exc.status_code,
        code=exc.code,
        message=str(exc),
        details=exc.details() or None,
    )


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


def _safe_header_value(field_names: list[str]) -> str:
    """Render field names as an ASCII-safe, comma-separated HTTP header value."""
    joined = ",".join(field_names)
    return joined.encode("ascii", "ignore").decode("ascii")


def _fill_report_headers(report: FillReport) -> dict[str, str]:
    """Expose fill outcome via response headers.

    Lets clients detect non-required fields that were dropped (for example,
    flagged for review) instead of receiving a silently incomplete PDF. Callers
    that want the full structured report should request ``application/json``.
    """
    return {
        "X-PDF-Fields-Written": str(len(report.written_fields)),
        "X-PDF-Fields-Skipped-Review": _safe_header_value(report.skipped_review_fields),
        "X-PDF-Fields-Skipped-Empty": _safe_header_value(report.skipped_empty_fields),
        "X-PDF-Fields-Skipped-Invalid": _safe_header_value(report.skipped_invalid_fields),
        "X-PDF-Flattened": str(report.flattened).lower(),
    }


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
        "audit action=fill request_id=%s auth=%s key=%s fields_total=%d fields_written=%d "
        "fields_review_skipped=%d fields_empty_skipped=%d fields_invalid_skipped=%d "
        "missing_required=%d semantic_inference=%s fallback_mapping=%s flattened=%s",
        request_id,
        "enabled" if settings.auth_enabled else "disabled",
        getattr(request.state, "api_key_name", "-"),
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

    metrics.increment("pdf_autofiller_fields_written_total", len(report.written_fields))
    metrics.increment(
        "pdf_autofiller_fields_skipped_total", len(report.skipped_review_fields), reason="review"
    )
    metrics.increment(
        "pdf_autofiller_fields_skipped_total", len(report.skipped_empty_fields), reason="empty"
    )
    metrics.increment(
        "pdf_autofiller_fields_skipped_total", len(report.skipped_invalid_fields), reason="invalid"
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
            "detail": _api_error_payload(
                code="request_validation_error",
                message="Request validation failed",
                details={"errors": exc.errors()},
            )
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
    if get_settings().metrics_enabled:
        metrics.observe(
            "pdf_autofiller_request_duration_seconds",
            elapsed,
            endpoint=request.url.path,
            method=request.method,
        )
    return response


# Per-client request timestamps for the sliding-window rate limiter. This is an
# in-process guard suitable for a single worker; multi-worker deployments should
# add a shared limiter (e.g. at the ingress/proxy layer).
_rate_limit_state: dict[str, deque[float]] = defaultdict(deque)


def _reset_rate_limit_state() -> None:
    """Clear rate-limiter state (used by tests)."""
    _rate_limit_state.clear()


def _client_identifier(request: Request) -> str:
    """Resolve the client key used for rate limiting."""
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _purge_stale_rate_limit_clients(now: float) -> None:
    """Drop idle client buckets to bound memory use under rotating clients."""
    if len(_rate_limit_state) <= 1000:
        return
    stale_clients = [
        client_id
        for client_id, window in _rate_limit_state.items()
        if not window or now - window[-1] >= 60.0
    ]
    for client_id in stale_clients:
        _rate_limit_state.pop(client_id, None)


async def _read_bounded_upload(upload: UploadFile, max_bytes: int) -> bytes:
    """Read an upload in chunks and reject payloads before they fully buffer."""
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await upload.read(UPLOAD_CHUNK_BYTES)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise _api_error(
                status_code=413,
                code="payload_too_large",
                message="PDF exceeds MAX_UPLOAD_BYTES limit",
                details={"max_upload_bytes": max_bytes},
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _measure_depth(value: Any, depth: int = 0) -> int:
    """Return the maximum nesting depth of a decoded JSON value."""
    if isinstance(value, dict):
        return max((_measure_depth(v, depth + 1) for v in value.values()), default=depth)
    if isinstance(value, list):
        return max((_measure_depth(v, depth + 1) for v in value), default=depth)
    return depth


def _count_keys(value: Any) -> int:
    """Return the total number of keys across a nested JSON value."""
    if isinstance(value, dict):
        return len(value) + sum(_count_keys(v) for v in value.values())
    if isinstance(value, list):
        return sum(_count_keys(v) for v in value)
    return 0


def _parse_user_data(raw: str, settings: Settings) -> dict[str, Any]:
    """Decode and bound the JSON payload accompanying an upload.

    The upload path was carefully bounded while this field beside it was an
    unbounded string handed straight to ``json.loads``. Size is checked before
    decoding; shape is checked after, because a small string can decode into a
    deeply nested structure that is expensive to walk.
    """
    encoded_length = len(raw.encode("utf-8"))
    if encoded_length > settings.max_user_data_bytes:
        raise UserDataTooLargeError(
            f"payload is {encoded_length} bytes", settings.max_user_data_bytes
        )

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _api_error(
            status_code=422,
            code="invalid_user_data_json",
            message="Invalid user_data JSON",
            details={"reason": str(exc)},
        ) from exc

    if not isinstance(parsed, dict):
        raise _api_error(
            status_code=422,
            code="invalid_user_data_type",
            message="user_data must be a JSON object",
        )

    depth = _measure_depth(parsed)
    if depth > settings.max_user_data_depth:
        raise UserDataTooLargeError(f"nesting depth {depth}", settings.max_user_data_depth)

    key_count = _count_keys(parsed)
    if key_count > settings.max_user_data_keys:
        raise UserDataTooLargeError(f"{key_count} keys", settings.max_user_data_keys)

    return parsed


def _parse_optional_json_object(raw: Optional[str], field: str) -> dict[str, Any]:
    """Decode an optional JSON-object form field."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _api_error(
            status_code=422,
            code="invalid_json",
            message=f"Invalid {field} JSON",
            details={"reason": str(exc)},
        ) from exc
    if not isinstance(parsed, dict):
        raise _api_error(
            status_code=422,
            code="invalid_json_type",
            message=f"{field} must be a JSON object",
        )
    return parsed


def _enforce_rate_limit(request: Request) -> None:
    """Apply a per-client sliding-window rate limit, if enabled."""
    limit = get_settings().rate_limit_per_minute
    if limit <= 0:
        return

    client_host = _client_identifier(request)
    now = time.monotonic()
    _purge_stale_rate_limit_clients(now)
    window = _rate_limit_state[client_host]
    while window and now - window[0] >= 60.0:
        window.popleft()

    if len(window) >= limit:
        raise _api_error(
            status_code=429,
            code="rate_limited",
            message="Too many requests",
            details={"limit_per_minute": limit},
        )

    window.append(now)


def _require_api_key(request: Request) -> None:
    """Validate API key auth when enabled."""
    settings = get_settings()
    if not settings.auth_enabled:
        request.state.api_key_name = "anonymous"
        return

    if not settings.auth_configured():
        logger.error("Authentication is enabled but no API keys are configured")
        raise _api_error(
            status_code=500,
            code="server_auth_config_error",
            message="Server authentication configuration error",
        )

    presented = request.headers.get(settings.api_key_header)
    key_name = settings.resolve_key(presented)
    if key_name is None:
        raise _api_error(status_code=401, code="unauthorized", message="Unauthorized")
    request.state.api_key_name = key_name


def _guard(request: Request) -> None:
    """Rate-limit then authenticate a mutating request."""
    _enforce_rate_limit(request)
    _require_api_key(request)


async def _run_pipeline(func, *args, **kwargs) -> Any:
    """Run a pipeline entry point in a killable worker, off the event loop."""
    settings = get_settings()
    try:
        return await asyncio.to_thread(
            run_isolated,
            func,
            *args,
            timeout=settings.pdf_read_timeout_seconds,
            **kwargs,
        )
    except PdfAutofillerError as exc:
        raise _domain_error(exc) from exc


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


@app.get("/metrics", response_class=PlainTextResponse)
def metrics_endpoint() -> PlainTextResponse:
    """Expose counters and histograms in Prometheus text format."""
    if not get_settings().metrics_enabled:
        raise _api_error(status_code=404, code="metrics_disabled", message="Metrics are disabled")
    return PlainTextResponse(content=metrics.render(), media_type="text/plain; version=0.0.4")


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

        resolved_data, resolved_overrides, stored_template = resolve_fill_inputs(
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
            strict=strict if stored_template is None else stored_template.strict,
            allow_fallback_mapping=allow_fallback_mapping,
            use_semantic_inference=use_semantic_inference,
            max_pages=settings.max_pdf_pages,
            max_text_chars=settings.max_pdf_text_chars,
            overrides=resolved_overrides,
        )
        metrics.increment("pdf_autofiller_inspects_total", outcome="success")
        return report
    except HTTPException:
        metrics.increment("pdf_autofiller_inspects_total", outcome="client_error")
        raise
    except PdfAutofillerError as exc:
        metrics.increment("pdf_autofiller_inspects_total", outcome="client_error")
        raise _domain_error(exc) from exc
    except Exception as exc:
        logger.exception("PDF inspect request failed")
        metrics.increment("pdf_autofiller_inspects_total", outcome="server_error")
        raise _api_error(
            status_code=500, code="pdf_inspect_failed", message="PDF inspect failed"
        ) from exc
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
        await pdf_file.close()


async def _stage_upload(pdf_file: UploadFile, settings: Settings):
    """Validate and write an upload to a temp directory, returning both."""
    import tempfile

    if pdf_file.content_type not in ("application/pdf", "application/octet-stream"):
        raise _api_error(
            status_code=415, code="unsupported_media_type", message="Expected a PDF upload"
        )

    temp_dir = tempfile.TemporaryDirectory(prefix="pdf-autofiller-")
    try:
        content = await _read_bounded_upload(pdf_file, settings.max_upload_bytes)
        if not content.startswith(b"%PDF-"):
            raise _api_error(
                status_code=415,
                code="invalid_pdf_signature",
                message="Uploaded file is not a valid PDF",
            )
        input_path = Path(temp_dir.name) / "input.pdf"
        input_path.write_bytes(content)
        return temp_dir, input_path
    except Exception:
        temp_dir.cleanup()
        raise


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
            strict = stored_template.strict
            allow_fallback_mapping = stored_template.allow_fallback_mapping
            use_semantic_inference = (
                use_semantic_inference or stored_template.use_semantic_inference
            )
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
        metrics.increment("pdf_autofiller_fills_total", outcome="success")

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
        metrics.increment("pdf_autofiller_fills_total", outcome="client_error")
        raise
    except PdfAutofillerError as exc:
        metrics.increment("pdf_autofiller_fills_total", outcome="client_error")
        raise _domain_error(exc) from exc
    except Exception as exc:
        logger.exception("PDF fill request failed")
        metrics.increment("pdf_autofiller_fills_total", outcome="server_error")
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


# --- batch -----------------------------------------------------------------


@router.post("/batch")
async def submit_batch_fill(
    request: Request,
    pdf_file: UploadFile = File(...),
    items: str = Form(...),
    strict: bool = Form(True),
    use_semantic_inference: bool = Form(False),
    flatten: bool = Form(False),
    output_dir: str = Form(""),
) -> dict[str, Any]:
    """
    Fill one form repeatedly, once per data item, in the background.

    ``items`` is a JSON array of ``{"name": ..., "user_data": {...}}`` objects.
    Returns a job ID immediately; poll the job endpoint for per-item status.
    """
    settings = get_settings()
    _guard(request)

    parsed = _parse_optional_json_list(items)
    if len(parsed) > settings.max_batch_items:
        raise _api_error(
            status_code=413,
            code="batch_too_large",
            message="Batch exceeds the maximum item count",
            details={"max_batch_items": settings.max_batch_items, "submitted": len(parsed)},
        )

    from .jobs import submit_batch

    # The batch outlives the request, so the upload is copied somewhere the
    # request-scoped temp directory cannot take away underneath it.
    import shutil
    import tempfile

    work_dir = Path(tempfile.mkdtemp(prefix="pdf-autofiller-batch-"))
    staged_dir, staged_input = await _stage_upload(pdf_file, settings)
    try:
        source_pdf = work_dir / "source.pdf"
        shutil.copyfile(staged_input, source_pdf)
    finally:
        staged_dir.cleanup()
        await pdf_file.close()

    destination = Path(output_dir).expanduser() if output_dir else work_dir / "out"
    destination.mkdir(parents=True, exist_ok=True)

    def worker(item: dict[str, Any]) -> dict[str, Any]:
        name = str(item.get("name", "item"))
        from .store import sanitize_name

        out_path = destination / f"{sanitize_name(name)}_filled.pdf"
        report, _, _ = run_isolated(
            run_fill_pipeline,
            source_pdf,
            out_path,
            item.get("user_data", {}),
            timeout=settings.pdf_read_timeout_seconds,
            strict=strict,
            use_semantic_inference=use_semantic_inference,
            max_pages=settings.max_pdf_pages,
            max_text_chars=settings.max_pdf_text_chars,
            overrides=item.get("overrides"),
            flatten=flatten,
        )
        return {
            "output_path": str(out_path),
            "fields_written": len(report.written_fields),
            "fields_skipped": len(report.skipped_review_fields)
            + len(report.skipped_empty_fields)
            + len(report.skipped_invalid_fields),
        }

    job = submit_batch(parsed, worker)
    return dict(job.model_dump())


def _parse_optional_json_list(raw: str) -> list[dict[str, Any]]:
    """Decode the batch item array."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _api_error(
            status_code=422,
            code="invalid_items_json",
            message="Invalid items JSON",
            details={"reason": str(exc)},
        ) from exc
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise _api_error(
            status_code=422,
            code="invalid_items_type",
            message="items must be a JSON array of objects",
        )
    return parsed


@router.get("/batch/{job_id}")
def get_batch_job(request: Request, job_id: str) -> dict[str, Any]:
    """Report a batch job's current state."""
    _guard(request)
    from .jobs import get_job

    job = get_job(job_id)
    if job is None:
        raise _api_error(status_code=404, code="job_not_found", message="Batch job not found")
    return dict(job.model_dump())


@router.get("/batch")
def list_batch_jobs(request: Request) -> dict[str, Any]:
    """List retained batch jobs, newest first."""
    _guard(request)
    from .jobs import list_jobs

    return {"jobs": [job.model_dump() for job in list_jobs()]}


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
