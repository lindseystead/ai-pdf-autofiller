"""Base class for every error the library raises on purpose."""


class PdfAutofillerError(Exception):
    """Catch this to handle any expected pdf_autofiller failure (bad PDF, limits, unresolved fields)."""


class ConflictingOptionsError(PdfAutofillerError, ValueError):
    """``strict=True`` and ``allow_fallback_mapping=True`` were both requested.

    Also a ``ValueError``, so handlers written against the previous exception type still catch it.
    """


class RecordsError(PdfAutofillerError, ValueError):
    """A batch input (JSON array, JSONL, or CSV) cannot be used.

    ``code`` is ``invalid_records`` or ``too_many_records``. Also a ``ValueError``.
    """

    def __init__(self, message: str, *, code: str = "invalid_records") -> None:
        self.code = code
        super().__init__(message)
