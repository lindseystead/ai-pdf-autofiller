"""
PDF Autofiller — fill AcroForm PDFs from JSON with deterministic-first mapping.

Public surface:
- ``fill`` / ``fill_batch`` / ``fill_template`` / ``preview_batch`` /
  ``fill_detailed`` / ``inspect`` / ``preview`` — local library (no server)
- ``PDFAutofillerClient`` — HTTP client for a running API
- ``PdfAutofillerError`` — base of every error raised on purpose (subclasses listed in ``__all__``)

``run_fill_pipeline`` stays importable from ``pdf_autofiller.pipeline`` for the API and
the corpus runner. It is not part of this package's public surface.
"""

__version__ = "0.8.0"

from .client import PDFAutofillerClient, PDFAutofillerClientError, PDFAutofillError
from .errors import ConflictingOptionsError, PdfAutofillerError, RecordsError
from .pdf_reader import InvalidPdfError, PdfPageLimitError
from .pdf_writer import UnresolvedRequiredFieldsError
from .pipeline import fill, fill_batch, fill_detailed, fill_template, inspect, preview, preview_batch
from .user_data import UserDataTooDeepError

__all__ = [
    "ConflictingOptionsError",
    "InvalidPdfError",
    "PDFAutofillError",
    "PDFAutofillerClient",
    "PDFAutofillerClientError",
    "PdfAutofillerError",
    "PdfPageLimitError",
    "RecordsError",
    "UnresolvedRequiredFieldsError",
    "UserDataTooDeepError",
    "__version__",
    "fill",
    "fill_batch",
    "fill_detailed",
    "fill_template",
    "inspect",
    "preview",
    "preview_batch",
]
