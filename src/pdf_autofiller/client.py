"""HTTP client for the PDF Autofiller API."""

from __future__ import annotations

import json
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

import httpx

from . import __version__


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

    def _pdf_upload(
        self,
        pdf: str | Path | bytes,
        *,
        filename: str | None = None,
    ) -> tuple[dict[str, tuple[str, bytes, str]], str]:
        if isinstance(pdf, (str, Path)):
            pdf_path = Path(pdf)
            pdf_bytes = pdf_path.read_bytes()
            upload_name = filename or pdf_path.name
        else:
            pdf_bytes = pdf
            upload_name = filename or "upload.pdf"
        return {"pdf_file": (upload_name, pdf_bytes, "application/pdf")}, upload_name

    def inspect(self, pdf: str | Path | bytes, *, filename: str | None = None) -> dict[str, Any]:
        """List AcroForm fields via ``POST /inspect``."""
        files, _name = self._pdf_upload(pdf, filename=filename)
        with self._client() as http:
            response = http.post(
                f"{self.base_url}/inspect",
                headers=self._headers(),
                files=files,
            )
        if response.status_code != 200:
            self._raise_api_error(response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise PDFAutofillError(500, "invalid_response", "Inspect endpoint returned non-object JSON")
        return payload

    def preview(
        self,
        pdf: str | Path | bytes,
        user_data: dict[str, Any],
        *,
        strict: bool = True,
        allow_fallback_mapping: bool = False,
        use_semantic_inference: bool = False,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """Return mapping decisions via ``POST /preview`` (no PDF write)."""
        files, _name = self._pdf_upload(pdf, filename=filename)
        data = {
            "user_data": json.dumps(user_data),
            "strict": str(strict).lower(),
            "allow_fallback_mapping": str(allow_fallback_mapping).lower(),
            "use_semantic_inference": str(use_semantic_inference).lower(),
        }
        with self._client() as http:
            response = http.post(
                f"{self.base_url}/preview",
                headers=self._headers(),
                files=files,
                data=data,
            )
        if response.status_code != 200:
            self._raise_api_error(response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise PDFAutofillError(500, "invalid_response", "Preview endpoint returned non-object JSON")
        return payload

    def fill(
        self,
        pdf: str | Path | bytes,
        user_data: dict[str, Any],
        *,
        strict: bool = True,
        allow_fallback_mapping: bool = False,
        use_semantic_inference: bool = False,
        flatten: bool = False,
        need_appearances: bool = True,
        filename: str | None = None,
        accept: str = "application/pdf",
    ) -> tuple[bytes | dict[str, Any], dict[str, str]]:
        """
        Fill a PDF from user data.

        When ``accept`` is ``application/pdf`` (default), returns
        ``(pdf_bytes, headers)``. When ``accept`` is ``application/json``,
        returns ``(report_dict, headers)`` including ``pdf_base64``.
        """
        files, _name = self._pdf_upload(pdf, filename=filename)
        data = {
            "user_data": json.dumps(user_data),
            "strict": str(strict).lower(),
            "allow_fallback_mapping": str(allow_fallback_mapping).lower(),
            "use_semantic_inference": str(use_semantic_inference).lower(),
            "flatten": str(flatten).lower(),
            "need_appearances": str(need_appearances).lower(),
        }
        headers = self._headers()
        headers["Accept"] = accept

        with self._client() as http:
            response = http.post(
                f"{self.base_url}/fill",
                headers=headers,
                files=files,
                data=data,
            )

        if response.status_code != 200:
            self._raise_api_error(response)

        response_headers = dict(response.headers)
        if accept.startswith("application/json"):
            payload = response.json()
            if not isinstance(payload, dict):
                raise PDFAutofillError(500, "invalid_response", "Fill JSON response was not an object")
            return payload, response_headers
        return response.content, response_headers

    def _client(self) -> AbstractContextManager[httpx.Client]:
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
        kwargs.setdefault("accept", "application/pdf")
        filled, headers = self.fill(pdf, user_data, **kwargs)
        if not isinstance(filled, (bytes, bytearray)):
            raise PDFAutofillError(
                500,
                "invalid_response",
                "fill_to_file requires Accept: application/pdf",
            )
        output_path = Path(output)
        output_path.write_bytes(bytes(filled))
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
