"""Base class for every error the library raises on purpose."""


class PdfAutofillerError(Exception):
    """Catch this to handle any expected pdf_autofiller failure (bad PDF, limits, unresolved fields)."""
