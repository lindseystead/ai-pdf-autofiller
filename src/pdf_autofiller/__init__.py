"""
PDF Autofiller — fill AcroForm PDFs from JSON with deterministic-first mapping.

Public surface:
- ``fill`` / ``fill_detailed`` / ``inspect`` / ``preview`` — local library (no server)
- ``PDFAutofillerClient`` — optional HTTP client for a running API
"""

__version__ = "0.6.3"

from .client import PDFAutofillerClient, PDFAutofillError
from .pipeline import fill, fill_detailed, inspect, preview, run_fill_pipeline

__all__ = [
    "PDFAutofillError",
    "PDFAutofillerClient",
    "__version__",
    "fill",
    "fill_detailed",
    "inspect",
    "preview",
    "run_fill_pipeline",
]
