"""
PDF Autofiller — fill AcroForm PDFs from JSON with deterministic-first mapping.

Public surface:
- ``fill`` / ``fill_detailed`` / ``inspect`` / ``preview`` — local library (no server)
- ``PDFAutofillerClient`` — HTTP client for a running API
- ``PdfAutofillerError`` — base of every error raised on purpose (subclasses listed in ``__all__``)
"""

__version__ = "0.7.0"

from .client import PDFAutofillerClient, PDFAutofillError
from .errors import PdfAutofillerError
from .pdf_reader import InvalidPdfError, PdfPageLimitError
from .pdf_writer import UnresolvedRequiredFieldsError
from .pipeline import fill, fill_detailed, inspect, preview, run_fill_pipeline
from .user_data import UserDataTooDeepError

__all__ = [
    "InvalidPdfError",
    "PDFAutofillError",
    "PDFAutofillerClient",
    "PdfAutofillerError",
    "PdfPageLimitError",
    "UnresolvedRequiredFieldsError",
    "UserDataTooDeepError",
    "__version__",
    "fill",
    "fill_detailed",
    "inspect",
    "preview",
    "run_fill_pipeline",
]
