"""Request middleware and logging setup."""

from __future__ import annotations

import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from . import config


class JsonLogFormatter(logging.Formatter):
    """Emit one JSON object per log line (no PII beyond the message text)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "time": self.formatTime(record, self.datefmt),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)


def configure_logging() -> None:
    """Apply text or JSON logging based on LOG_FORMAT."""
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler()
        if config.LOG_FORMAT == "json":
            handler.setFormatter(JsonLogFormatter())
        else:
            handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
        root.addHandler(handler)
    root.setLevel(config.resolve_log_level())


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach baseline security headers without breaking the playground HTML."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response


async def request_context_middleware(request: Request, call_next):
    """Attach request ID and emit basic request logs."""
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    logging.getLogger("pdf_autofiller.api").info(
        "request_id=%s method=%s path=%s status=%s duration_ms=%.2f",
        request_id,
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


def install_middleware(app: FastAPI) -> None:
    """Register middleware on the FastAPI app."""
    app.add_middleware(SecurityHeadersMiddleware)
    app.middleware("http")(request_context_middleware)
