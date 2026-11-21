"""Base class for every error the library raises on purpose."""


class PdfAutofillerError(Exception):
    """Catch this to handle any expected pdf_autofiller failure (bad PDF, limits, unresolved fields)."""


class ConflictingOptionsError(PdfAutofillerError, ValueError):
    """``strict=True`` and ``allow_fallback_mapping=True`` were both requested.

    Also a ``ValueError``, so handlers written against the previous exception type still catch it.
    """
