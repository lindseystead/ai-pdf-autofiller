"""
PDF extraction utilities.

This module is intentionally extraction-only: it reads metadata, fields, and text,
and does not perform any semantic inference.

Because it parses untrusted documents, it enforces denial-of-service guards: an
optional page-count limit (rejected before any extraction) and a cap on the
total volume of text retained and forwarded downstream.

It also refuses documents it cannot honestly fill. An encrypted PDF and an XFA
PDF both used to reach the mapper as "a form with zero fields", which produced a
required-fields error pointing at the wrong problem. Both now raise named errors.
"""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from . import acroform_fields
from .errors import (
    EncryptedPdfError,
    PdfParseError,
    PdfPageLimitError,
    XfaFormError,
)
from .models import DocumentMetadata, DocumentStructure, FormField, TextRegion

_extract_form_fields = acroform_fields.extract_form_fields
_get_field_type = acroform_fields.get_field_type
_get_field_value = acroform_fields.get_field_value

logger = logging.getLogger(__name__)

MAX_TOTAL_TEXT_CHARS = int(os.getenv("MAX_PDF_TEXT_CHARS", str(2_000_000)))

__all__ = [
    "read_pdf",
    "open_reader",
    "form_fingerprint",
    "PdfPageLimitError",
    "MAX_TOTAL_TEXT_CHARS",
]


def _metadata_value(metadata: dict[str, object], key: str) -> Optional[str]:
    """Read and normalize metadata values as strings."""
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _extract_text_regions(
    reader: PdfReader, max_chars: Optional[int] = None
) -> list[TextRegion]:
    """Extract visible text content from all PDF pages.

    ``max_chars`` resolves at call time rather than as a default argument so the
    module-level budget stays overridable at runtime.
    """
    if max_chars is None:
        max_chars = MAX_TOTAL_TEXT_CHARS
    text_regions = []
    total_chars = 0

    for page_num, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text()
            if text and text.strip():
                stripped = text.strip()
                remaining = max_chars - total_chars
                if remaining <= 0:
                    logger.warning(
                        "Extracted text reached %d-char limit; truncating remaining pages",
                        max_chars,
                    )
                    break
                if len(stripped) > remaining:
                    stripped = stripped[:remaining]
                total_chars += len(stripped)
                text_regions.append(TextRegion(text=stripped, page_number=page_num))
        except Exception:
            logger.debug("Failed to extract text from page %s", page_num, exc_info=True)
            continue

    return text_regions


def _has_xfa(reader: PdfReader) -> bool:
    """Detect an XFA form without touching reader.xfa.

    ``reader.xfa`` decompresses the XFA payload, which was a memory-exhaustion
    vector (fixed in pypdf 6.7.3, but there is no reason to decompress it here).
    Checking for the ``/XFA`` key on the AcroForm dictionary is enough.
    """
    try:
        root = reader.trailer["/Root"]
        acroform = root.get("/AcroForm")
        if acroform is None:
            return False
        if hasattr(acroform, "get_object"):
            acroform = acroform.get_object()
        return "/XFA" in acroform
    except Exception:
        logger.debug("Could not inspect AcroForm for XFA", exc_info=True)
        return False


def open_reader(pdf_path: Path) -> PdfReader:
    """Open a PDF, raising typed errors for documents we cannot fill."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    try:
        reader = PdfReader(str(pdf_path))
    except PdfReadError as exc:
        raise PdfParseError(str(exc)) from exc
    except Exception as exc:  # malformed input surfaces in many shapes
        raise PdfParseError(str(exc)) from exc

    # getattr keeps this tolerant of reader objects that predate the attribute.
    if getattr(reader, "is_encrypted", False):
        # An empty user password is common and harmless; try it before refusing.
        try:
            if not reader.decrypt(""):
                raise EncryptedPdfError()
        except EncryptedPdfError:
            raise
        except Exception as exc:
            raise EncryptedPdfError() from exc

    if _has_xfa(reader):
        has_fallback = False
        try:
            has_fallback = bool(reader.get_fields())
        except Exception:
            has_fallback = False
        raise XfaFormError(has_acroform_fallback=has_fallback)

    return reader


def form_fingerprint(fields: list[FormField]) -> str:
    """Stable hash of a form's field structure.

    Keyed on names, types, and required flags rather than file bytes, so the
    same government form re-downloaded (different timestamps, same structure)
    resolves to the same template and cached semantics.
    """
    payload = "\n".join(
        f"{field.name}|{field.field_type}|{int(field.required)}"
        for field in sorted(fields, key=lambda f: f.name)
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def read_pdf(
    pdf_path: Path,
    *,
    max_pages: Optional[int] = None,
    max_text_chars: Optional[int] = None,
) -> DocumentStructure:
    """Read a PDF and extract its complete structure."""
    reader = open_reader(pdf_path)

    num_pages = len(reader.pages)
    if max_pages is not None and num_pages > max_pages:
        raise PdfPageLimitError(num_pages=num_pages, max_pages=max_pages)

    metadata_dict: dict[str, object] = dict(reader.metadata or {})
    metadata = DocumentMetadata(
        num_pages=num_pages,
        title=_metadata_value(metadata_dict, "/Title"),
        author=_metadata_value(metadata_dict, "/Author"),
        subject=_metadata_value(metadata_dict, "/Subject"),
        creator=_metadata_value(metadata_dict, "/Creator"),
        producer=_metadata_value(metadata_dict, "/Producer"),
    )

    form_fields = _extract_form_fields(reader)
    text_regions = _extract_text_regions(reader, max_text_chars)

    return DocumentStructure(
        metadata=metadata,
        form_fields=form_fields,
        text_regions=text_regions,
    )
