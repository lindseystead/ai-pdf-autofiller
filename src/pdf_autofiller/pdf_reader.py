"""
PDF extraction utilities.

This module is intentionally extraction-only: it reads metadata, fields, and text,
and does not perform any semantic inference.

Because it parses untrusted documents, it enforces two denial-of-service guards:
an optional page-count limit (rejected before any extraction) and a cap on the
total volume of text retained and forwarded downstream.
"""

import logging
import os
from pathlib import Path
from typing import Optional

from pypdf import PdfReader

from . import acroform_fields
from .models import DocumentMetadata, DocumentStructure, TextRegion

_extract_form_fields = acroform_fields.extract_form_fields
_get_field_type = acroform_fields.get_field_type
_get_field_value = acroform_fields.get_field_value

logger = logging.getLogger(__name__)

MAX_TOTAL_TEXT_CHARS = int(os.getenv("MAX_PDF_TEXT_CHARS", str(2_000_000)))


class PdfPageLimitError(Exception):
    """Raised when a PDF has more pages than the configured limit allows."""

    def __init__(self, num_pages: int, max_pages: int):
        self.num_pages = num_pages
        self.max_pages = max_pages
        super().__init__(
            f"PDF has {num_pages} pages, exceeding the limit of {max_pages}"
        )


def _metadata_value(metadata: dict[str, object], key: str) -> Optional[str]:
    """Read and normalize metadata values as strings."""
    value = metadata.get(key)
    return value if isinstance(value, str) else None


def _extract_text_regions(reader: PdfReader) -> list[TextRegion]:
    """Extract visible text content from all PDF pages."""
    text_regions = []
    total_chars = 0

    for page_num, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text()
            if text and text.strip():
                stripped = text.strip()
                remaining = MAX_TOTAL_TEXT_CHARS - total_chars
                if remaining <= 0:
                    logger.warning(
                        "Extracted text reached %d-char limit; truncating remaining pages",
                        MAX_TOTAL_TEXT_CHARS,
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


def read_pdf(pdf_path: Path, *, max_pages: Optional[int] = None) -> DocumentStructure:
    """Read a PDF and extract its complete structure."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")

    reader = PdfReader(str(pdf_path))

    num_pages = len(reader.pages)
    if max_pages is not None and num_pages > max_pages:
        raise PdfPageLimitError(num_pages=num_pages, max_pages=max_pages)

    metadata_dict: dict[str, object] = dict(reader.metadata or {})
    metadata = DocumentMetadata(
        num_pages=len(reader.pages),
        title=_metadata_value(metadata_dict, "/Title"),
        author=_metadata_value(metadata_dict, "/Author"),
        subject=_metadata_value(metadata_dict, "/Subject"),
        creator=_metadata_value(metadata_dict, "/Creator"),
        producer=_metadata_value(metadata_dict, "/Producer"),
    )

    form_fields = _extract_form_fields(reader)
    text_regions = _extract_text_regions(reader)

    return DocumentStructure(
        metadata=metadata,
        form_fields=form_fields,
        text_regions=text_regions,
    )
