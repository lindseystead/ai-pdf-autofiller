"""
Public ASGI and console-script entrypoint for the HTTP service.

The implementation lives in ``pdf_autofiller.api``; deployments point at
``pdf_autofiller.api_service:app`` (Dockerfile, Makefile, ``pdf-autofiller-api``).
"""

from __future__ import annotations

from .api.app import app, create_app, run

__all__ = ["app", "create_app", "run"]
