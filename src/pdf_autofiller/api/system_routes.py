"""Public playground, health, version, and sample-document routes."""

from fastapi import APIRouter, Response
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from pdf_autofiller import __version__
from pdf_autofiller.mapping import alias_pack_status
from pdf_autofiller.pipeline import semantic_provider_status
from pdf_autofiller.playground import PLAYGROUND_CSS_PATH, PLAYGROUND_HTML, PLAYGROUND_JS_PATH

from . import config
from .errors import api_error
from .route_support import _sample_form_path
from .schemas import HealthResponse, VersionResponse
from .security import rate_limit_health_status

router = APIRouter()


@router.get("/")
def root() -> RedirectResponse:
    """Redirect browsers to the interactive playground."""
    return RedirectResponse(url="/playground")


@router.get("/playground", response_class=HTMLResponse)
def playground_page() -> HTMLResponse:
    """Serve the browser playground for trying fills without curl."""
    return HTMLResponse(content=PLAYGROUND_HTML)


@router.get("/assets/playground.css", include_in_schema=False)
def playground_css() -> FileResponse:
    return FileResponse(
        PLAYGROUND_CSS_PATH,
        media_type="text/css",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/assets/playground.js", include_in_schema=False)
def playground_javascript() -> FileResponse:
    return FileResponse(
        PLAYGROUND_JS_PATH,
        media_type="text/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@router.get("/health", response_model=HealthResponse)
def health(response: Response) -> HealthResponse:
    checks = {
        "auth": (
            "enabled"
            if config.API_AUTH_ENABLED and config.API_AUTH_TOKEN
            else "disabled"
            if not config.API_AUTH_ENABLED
            else "misconfigured"
        ),
        "semantic_provider": semantic_provider_status(),
        "rate_limit": rate_limit_health_status(),
        **alias_pack_status(),
    }
    status = "ok" if checks["auth"] != "misconfigured" else "degraded"
    if status == "degraded":
        response.status_code = 503
    return HealthResponse(
        status=status,
        service="pdf-autofiller",
        version=__version__,
        checks=checks,
    )


@router.get("/version", response_model=VersionResponse)
def version() -> VersionResponse:
    return VersionResponse(service="pdf-autofiller", version=__version__)


@router.get("/samples/sample_form.pdf")
def sample_form_pdf() -> FileResponse:
    """Serve the bundled sample AcroForm for playground one-click demos."""
    sample = _sample_form_path()
    if sample is None:
        raise api_error(
            status_code=404,
            code="sample_not_found",
            message="Sample PDF is not bundled in this deployment",
        )
    return FileResponse(
        path=sample,
        media_type="application/pdf",
        filename="sample_form.pdf",
    )
