"""HTTP client for the PDF Autofiller API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ContextManager

import httpx

from . import __version__
from .pipeline import run_fill_pipeline


class _BorrowedClient:
    """Context manager that yields an injected client without closing it."""

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def __enter__(self) -> httpx.Client:
        return self._client

    def __exit__(self, *args: object) -> None:
        return None


class PDFAutofillError(Exception):
    """Raised when the API returns an error response."""

    def __init__(self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None):
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"{code}: {message}")


class PDFAutofillerClient:
    """Simple client for the PDF Autofiller fill endpoint."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        api_key: str | None = None,
        api_key_header: str = "X-API-Key",
        timeout_seconds: float = 60.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_key_header = api_key_header
        self.timeout_seconds = timeout_seconds
        self._http_client = http_client

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"User-Agent": f"pdf-autofiller-client/{__version__}"}
        if self.api_key:
            headers[self.api_key_header] = self.api_key
        return headers

    def health(self) -> dict[str, Any]:
        """Return service health metadata."""
        with self._client() as http:
            response = http.get(f"{self.base_url}/health", headers=self._headers())
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise PDFAutofillError(500, "invalid_response", "Health endpoint returned non-object JSON")
            return payload

    def fill(
        self,
        pdf: str | Path | bytes,
        user_data: dict[str, Any],
        *,
        strict: bool = True,
        allow_fallback_mapping: bool = False,
        use_semantic_inference: bool = False,
        filename: str | None = None,
    ) -> tuple[bytes, dict[str, str]]:
        """
        Fill a PDF from user data and return the filled PDF bytes plus response headers.

        Args:
            pdf: Path to a PDF file or raw PDF bytes
            user_data: JSON-serializable mapping of profile fields
            strict: Disable fallback mapping when True
            allow_fallback_mapping: Enable provider-backed fallback for unresolved fields
            use_semantic_inference: Run semantic inference before mapping
            filename: Optional upload filename when pdf is bytes

        Returns:
            Tuple of (filled_pdf_bytes, response_headers)
        """
        if isinstance(pdf, (str, Path)):
            pdf_path = Path(pdf)
            pdf_bytes = pdf_path.read_bytes()
            upload_name = filename or pdf_path.name
        else:
            pdf_bytes = pdf
            upload_name = filename or "upload.pdf"

        files = {"pdf_file": (upload_name, pdf_bytes, "application/pdf")}
        data = {
            "user_data": json.dumps(user_data),
            "strict": str(strict).lower(),
            "allow_fallback_mapping": str(allow_fallback_mapping).lower(),
            "use_semantic_inference": str(use_semantic_inference).lower(),
        }

        with self._client() as http:
            response = http.post(
                f"{self.base_url}/fill",
                headers=self._headers(),
                files=files,
                data=data,
            )

        if response.status_code != 200:
            self._raise_api_error(response)

        return response.content, dict(response.headers)

    def _client(self) -> ContextManager[httpx.Client]:
        if self._http_client is not None:
            return _BorrowedClient(self._http_client)
        return httpx.Client(timeout=self.timeout_seconds)

    def fill_to_file(
        self,
        pdf: str | Path,
        user_data: dict[str, Any],
        output: str | Path,
        **kwargs: Any,
    ) -> dict[str, str]:
        """Fill a PDF and write the result to disk. Returns response headers."""
        filled_bytes, headers = self.fill(pdf, user_data, **kwargs)
        output_path = Path(output)
        output_path.write_bytes(filled_bytes)
        return headers

    @staticmethod
    def _raise_api_error(response: httpx.Response) -> None:
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            raise PDFAutofillError(
                response.status_code,
                "invalid_response",
                response.text or "Request failed",
            ) from exc

        detail = payload.get("detail", payload)
        if isinstance(detail, dict) and "error" in detail:
            error = detail["error"]
            raise PDFAutofillError(
                response.status_code,
                str(error.get("code", "api_error")),
                str(error.get("message", "Request failed")),
                error.get("details") if isinstance(error.get("details"), dict) else None,
            )

        raise PDFAutofillError(
            response.status_code,
            "api_error",
            str(detail),
        )


def fill(
    pdf: str | Path,
    user_data: dict[str, Any],
    output: str | Path,
    *,
    strict: bool = True,
    allow_fallback_mapping: bool = False,
    use_semantic_inference: bool = False,
    base_url: str | None = None,
    api_key: str | None = None,
) -> dict[str, str]:
    """
    Convenience helper: fill a PDF in three lines.

    By default this runs the local deterministic pipeline (no server required).
    Pass ``base_url`` to use the HTTP API instead (for remote deployments).

    Example::

        from pdf_autofiller import fill
        fill("form.pdf", {"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01"}, "filled.pdf")
    """
    if base_url is not None:
        client = PDFAutofillerClient(base_url=base_url, api_key=api_key)
        return client.fill_to_file(
            pdf,
            user_data,
            output,
            strict=strict,
            allow_fallback_mapping=allow_fallback_mapping,
            use_semantic_inference=use_semantic_inference,
        )

    report, _mapping, _field_count = run_fill_pipeline(
        Path(pdf),
        Path(output),
        user_data,
        strict=strict,
        allow_fallback_mapping=allow_fallback_mapping,
        use_semantic_inference=use_semantic_inference,
    )
    return {
        "X-PDF-Fields-Written": str(len(report.written_fields)),
        "X-PDF-Fields-Skipped-Review": ",".join(report.skipped_review_fields),
        "X-PDF-Fields-Skipped-Empty": ",".join(report.skipped_empty_fields),
    }
