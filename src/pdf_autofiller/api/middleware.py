"""Request middleware and logging setup."""

from __future__ import annotations

import json
import logging
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import config
from .errors import api_error
from .security import guard_mutating_request

UPLOAD_PATHS = frozenset({"/fill", "/preview", "/inspect", "/template", "/batch", "/v1/templates"})


def _is_upload_path(path: str) -> bool:
    normalized = path.rstrip("/") or "/"
    if normalized in UPLOAD_PATHS:
        return True
    parts = normalized.strip("/").split("/")
    return len(parts) == 4 and parts[0] == "v1" and parts[1] == "templates" and parts[3] == "versions"


def _is_product_mutation(method: str, path: str) -> bool:
    return method in {"POST", "PUT", "PATCH", "DELETE"} and path.rstrip("/").startswith("/v1/")


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

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; connect-src 'self'; img-src 'self' data:; "
            "style-src 'self'; script-src 'self'; "
            "object-src 'self' blob:; frame-src blob:; form-action 'self'; "
            "frame-ancestors 'none'; base-uri 'none'",
        )
        response.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        return response


async def request_context_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
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


class RequestGuardMiddleware:
    """Authenticate, rate-limit and size-check protected requests before reading the body.

    Route handlers only run after FastAPI has parsed JSON or spooled multipart
    bodies to disk, so checks in handlers would allow unbounded request bodies.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_upload = scope["method"] == "POST" and _is_upload_path(scope["path"])
        is_product_mutation = _is_product_mutation(scope["method"], scope["path"])
        if not is_upload and not is_product_mutation:
            await self.app(scope, receive, send)
            return

        limit = (
            config.MAX_UPLOAD_BYTES + config.FORM_OVERHEAD_BYTES if is_upload else config.JSON_BODY_MAX_BYTES
        )
        too_large = api_error(
            status_code=413,
            code="payload_too_large",
            message="Request body exceeds the upload limit",
            details={
                "max_body_bytes": limit,
                "max_upload_bytes": config.MAX_UPLOAD_BYTES if is_upload else None,
            },
        )
        request = Request(scope)
        try:
            guard_mutating_request(request)
            scope.setdefault("state", {})["security_guarded"] = True
            declared = request.headers.get("content-length", "")
            # isascii(): str.isdigit() also accepts "²" etc., which int() rejects.
            if declared.isascii() and declared.isdigit() and int(declared) > limit:
                raise too_large
        except HTTPException as exc:
            await _error_response(exc)(scope, receive, send)
            return

        # Content-Length may be absent or wrong, so also count what arrives.
        received = 0
        exceeded = False

        async def bounded_receive() -> Message:
            nonlocal received, exceeded
            if exceeded:
                return {"type": "http.disconnect"}
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    return {"type": "http.disconnect"}
            return message

        async def guarded_send(message: Message) -> None:
            if not exceeded:  # drop the app's reaction to the cut-off body
                await send(message)

        await self.app(scope, bounded_receive, guarded_send)
        if exceeded:
            await _error_response(too_large)(scope, receive, send)


def _error_response(exc: HTTPException) -> JSONResponse:
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)


def install_middleware(app: FastAPI) -> None:
    """Register middleware on the FastAPI app (the first added runs innermost)."""
    app.add_middleware(RequestGuardMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    app.middleware("http")(request_context_middleware)
