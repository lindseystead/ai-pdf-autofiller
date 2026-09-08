"""FastAPI application factory and process entrypoint."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from pdf_autofiller import __version__

from . import config
from .errors import api_error_payload
from .middleware import configure_logging, install_middleware
from .routes import router


def create_app() -> FastAPI:
    """Build the FastAPI application with middleware and routes."""
    application = FastAPI(
        title="PDF Autofiller API",
        version=__version__,
        description=(
            "HTTP API for deterministic-first PDF form filling with optional semantic inference."
        ),
    )
    install_middleware(application)

    @application.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(
        request, exc: RequestValidationError
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
    """Run local API server."""
    import uvicorn

    configure_logging()
    uvicorn.run(
        "pdf_autofiller.api_service:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        log_level=logging.getLevelName(config.resolve_log_level()).lower(),
    )
