"""
Typed domain errors for the fill pipeline.

Every failure a caller can act on gets its own class with a stable ``code``.
The HTTP layer maps ``code`` straight onto the API error contract, so adding an
error here is the only change needed to surface it to clients.

The point of naming these is diagnosis: an encrypted PDF and an XFA PDF both
used to surface as "zero fields found", which sent users looking for a mapping
problem that did not exist.
"""

from typing import Any


class PdfAutofillerError(Exception):
    """Base class for errors that map onto a client-visible API response."""

    code = "pdf_autofiller_error"
    status_code = 500

    def details(self) -> dict[str, Any]:
        """Structured payload attached to the API error response."""
        return {}


class PdfPageLimitError(PdfAutofillerError):
    """Raised when a PDF has more pages than the configured limit allows."""

    code = "pdf_too_many_pages"
    status_code = 413

    def __init__(self, num_pages: int, max_pages: int):
        self.num_pages = num_pages
        self.max_pages = max_pages
        super().__init__(f"PDF has {num_pages} pages, exceeding the limit of {max_pages}")

    def details(self) -> dict[str, Any]:
        return {"num_pages": self.num_pages, "max_pages": self.max_pages}


class EncryptedPdfError(PdfAutofillerError):
    """Raised when a PDF is encrypted and cannot be opened without a password."""

    code = "pdf_encrypted"
    status_code = 422

    def __init__(self) -> None:
        super().__init__(
            "PDF is password-protected. Remove the password before filling; "
            "this service does not accept document passwords."
        )


class XfaFormError(PdfAutofillerError):
    """Raised when a PDF uses an XFA form, which AcroForm tooling cannot fill.

    XFA is a separate XML form technology that lives alongside (and overrides)
    the AcroForm dictionary. Filling the AcroForm shell has no effect on what
    the user sees, so this must fail loudly rather than write a no-op document.
    """

    code = "pdf_xfa_unsupported"
    status_code = 422

    def __init__(self, *, has_acroform_fallback: bool = False):
        self.has_acroform_fallback = has_acroform_fallback
        super().__init__(
            "PDF uses an XFA form, which is not supported. Flatten it to a "
            "standard AcroForm (for example, print to PDF from Acrobat) first."
        )

    def details(self) -> dict[str, Any]:
        return {"has_acroform_fallback": self.has_acroform_fallback}


class NoFormFieldsError(PdfAutofillerError):
    """Raised when a PDF has no fillable fields at all."""

    code = "pdf_no_form_fields"
    status_code = 422

    def __init__(self) -> None:
        super().__init__(
            "PDF contains no fillable form fields. It may be a scanned or flattened "
            "document rather than an interactive form."
        )


class PdfParseError(PdfAutofillerError):
    """Raised when a PDF is malformed beyond recovery."""

    code = "pdf_parse_failed"
    status_code = 422

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"Could not parse PDF: {reason}")

    def details(self) -> dict[str, Any]:
        return {"reason": self.reason}


class PdfProcessingTimeoutError(PdfAutofillerError):
    """Raised when PDF processing exceeds its wall-clock budget."""

    code = "pdf_processing_timeout"
    status_code = 503

    def __init__(self, timeout_seconds: float):
        self.timeout_seconds = timeout_seconds
        super().__init__(f"PDF processing exceeded {timeout_seconds}s")

    def details(self) -> dict[str, Any]:
        return {"timeout_seconds": self.timeout_seconds}


class UnresolvedRequiredFieldsError(PdfAutofillerError):
    """Raised when required fields can't be filled.

    The pipeline refuses to emit a partially filled form: a document missing a
    required field is usually worse than no document, because it looks complete.
    """

    code = "required_fields_unresolved"
    status_code = 422

    def __init__(self, missing_fields: list[str], skipped_fields: list[str]):
        self.missing_fields = missing_fields
        self.skipped_fields = skipped_fields
        message_parts = []
        if missing_fields:
            message_parts.append(f"Missing required fields: {', '.join(missing_fields)}")
        if skipped_fields:
            message_parts.append(
                f"Skipped required fields (requires_review=True): {', '.join(skipped_fields)}"
            )
        super().__init__("; ".join(message_parts))

    def details(self) -> dict[str, Any]:
        return {
            "missing_fields": self.missing_fields,
            "skipped_fields": self.skipped_fields,
        }


class TemplateNotFoundError(PdfAutofillerError):
    """Raised when a named template does not exist in the store."""

    code = "template_not_found"
    status_code = 404

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Template not found: {name}")

    def details(self) -> dict[str, Any]:
        return {"template": self.name}


class ProfileNotFoundError(PdfAutofillerError):
    """Raised when a named profile does not exist in the store."""

    code = "profile_not_found"
    status_code = 404

    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Profile not found: {name}")

    def details(self) -> dict[str, Any]:
        return {"profile": self.name}


class UserDataTooLargeError(PdfAutofillerError):
    """Raised when submitted user data exceeds configured size or shape limits."""

    code = "user_data_too_large"
    status_code = 413

    def __init__(self, reason: str, limit: int):
        self.reason = reason
        self.limit = limit
        super().__init__(f"user_data rejected: {reason}")

    def details(self) -> dict[str, Any]:
        return {"reason": self.reason, "limit": self.limit}
