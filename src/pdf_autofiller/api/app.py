"""FastAPI application factory and process entrypoint."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from pdf_autofiller import __version__

from . import config
from .errors import api_error_payload
from .middleware import configure_logging, install_middleware
from .routes import router


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Runs when a server starts the app (uvicorn, Docker CMD, pdf-autofiller-api), not on import."""
    configure_logging()
    if config.API_AUTH_ENABLED and not config.API_AUTH_TOKEN:
        logging.getLogger(__name__).warning(
            "API_AUTH_TOKEN is not set, so /fill, /preview and /inspect will return 500. "
            "Set API_AUTH_TOKEN, or API_AUTH_ENABLED=false for local use."
        )
    yield


def create_app() -> FastAPI:
    """Build the FastAPI application with middleware and routes."""
    application = FastAPI(
        title="PDF Autofiller API",
        version=__version__,
        description=(
            "HTTP API for deterministic-first PDF form filling. "
            "AI field inference and the AI key fallback stay off unless a request asks for them."
        ),
        lifespan=_lifespan,
    )
    install_middleware(application)

    @application.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={
                "detail": api_error_payload(
                    code="request_validation_error",
                    message="Request validation failed",
                    details={"errors": exc.errors()},
                )
            },
        )

    application.include_router(router)
    return application


app = create_app()


def run() -> None:
    """Run the API for local use.

    Binds to ``127.0.0.1`` unless ``API_HOST`` is set. The Docker image does not
    use this entrypoint; its process listens on ``0.0.0.0`` inside the container
    and the published port decides who can reach it.
    """
    import uvicorn

    host = os.getenv("API_HOST", "127.0.0.1").strip() or "127.0.0.1"
    raw_port = os.getenv("API_PORT", "8000").strip() or "8000"
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise SystemExit(f"API_PORT must be an integer, got {raw_port!r}") from exc
    if port < 1 or port > 65535:
        raise SystemExit(f"API_PORT must be between 1 and 65535, got {port}")

    uvicorn.run(
        "pdf_autofiller.api_service:app",
        host=host,
        port=port,
        reload=False,
        log_level=logging.getLevelName(config.resolve_log_level()).lower(),
    )
