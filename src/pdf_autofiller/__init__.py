"""
Document engine for PDF processing.

This package provides tools for reading, analyzing, and filling PDF forms
with optional semantic inference.
"""

__version__ = "0.4.3"

from .client import PDFAutofillerClient, PDFAutofillError, fill

__all__ = ["PDFAutofillerClient", "PDFAutofillError", "fill", "__version__"]
