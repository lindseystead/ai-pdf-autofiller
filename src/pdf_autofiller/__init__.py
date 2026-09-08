"""
Document engine for PDF processing.

This package provides tools for reading, analyzing, and filling PDF forms
with optional semantic inference.
"""

__version__ = "0.5.0"

from .client import PDFAutofillerClient, PDFAutofillError
from .pipeline import fill, run_fill_pipeline

__all__ = [
    "PDFAutofillError",
    "PDFAutofillerClient",
    "__version__",
    "fill",
    "run_fill_pipeline",
]
