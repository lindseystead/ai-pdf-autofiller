"""
HTTP boundary for the PDF autofill service.

Implementation lives in ``pdf_autofiller.api``. This module remains the public
ASGI / console-script entrypoint (``pdf_autofiller.api_service:app``) and
re-exports symbols historically imported from here.
"""

from __future__ import annotations

from .api.app import app, create_app, run
from .api.errors import api_error as _api_error
from .api.errors import api_error_payload as _api_error_payload
from .api.security import reset_rate_limit_state as _reset_rate_limit_state
from .pdf_writer import UnresolvedRequiredFieldsError
from .pipeline import enrich_fields as _enrich_fields
from .pipeline import fallback_semantics as _fallback_semantics
from .pipeline import page_context_by_number as _page_context_by_number
from .pipeline import run_fill_pipeline, run_preview_pipeline

__all__ = [
    "UnresolvedRequiredFieldsError",
    "_api_error",
    "_api_error_payload",
    "_enrich_fields",
    "_fallback_semantics",
    "_page_context_by_number",
    "_reset_rate_limit_state",
    "app",
    "create_app",
    "run",
    "run_fill_pipeline",
    "run_preview_pipeline",
]
