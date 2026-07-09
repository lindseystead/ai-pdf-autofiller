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
from typing import Literal, Optional, cast

from pypdf import PdfReader
from pypdf.generic import IndirectObject

from .field_utils import is_field_required
from .models import DocumentMetadata, DocumentStructure, FormField, TextRegion

logger = logging.getLogger(__name__)

# Upper bound on total extracted page text retained and forwarded downstream
# (including to any provider for semantic context). Bounds memory and provider
# token usage for hostile or pathologically large documents. Note: this caps
# what is *kept*; peak per-page allocation is additionally bounded by the
# caller's processing time budget and container memory limits.
MAX_TOTAL_TEXT_CHARS = int(os.getenv("MAX_PDF_TEXT_CHARS", str(2_000_000)))


class PdfPageLimitError(Exception):
    """Raised when a PDF has more pages than the configured limit allows.

    Used as a cheap denial-of-service guard so hostile or accidental oversized
    documents are rejected before any expensive text extraction runs.
    """

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


def _get_field_type(field_obj) -> Literal["text", "button", "choice", "signature", "unknown"]:
    """
    Extract field type from PDF field object.
    
    PDF field types are encoded as PDF name objects like /Tx (text),
    /Btn (button), etc. This converts them to our internal string format.
    """
    ft = field_obj.get("/FT")
    if ft == "/Tx":
        return "text"
    elif ft == "/Btn":
        return "button"
    elif ft == "/Ch":
        return "choice"
    elif ft == "/Sig":
        return "signature"
    else:
        return "unknown"


def _get_field_value(field_obj) -> Optional[str]:
    """
    Extract current value from a PDF form field.
    
    PDF values can be stored as direct objects or indirect references.
    This handles both cases and converts to string representation.
    """
    v = field_obj.get("/V")
    if v is None:
        return None
    
    if isinstance(v, (str, bool, int, float)):
        return str(v)
    elif isinstance(v, IndirectObject):
        # Indirect objects need to be resolved first
        try:
            resolved = v.get_object()
            if isinstance(resolved, (str, bool, int, float)):
                return str(resolved)
        except Exception as exc:
            logger.debug("Failed to resolve indirect field value: %s", exc)
    
    return str(v) if v else None


def _find_field_page(reader: PdfReader, field_obj) -> int:
    """
    Determine which page a form field appears on.
    
    Fields can reference their parent page via the /P key. This tries
    to resolve that reference and match it to a page number. Falls back
    to page 1 if the reference can't be resolved.
    """
    if hasattr(field_obj, "get"):
        page_ref = field_obj.get("/P")
        if page_ref:
            try:
                if hasattr(page_ref, "get_object"):
                    page_obj = page_ref.get_object()
                else:
                    page_obj = page_ref
                
                # Match page object to page number
                for idx, page in enumerate(reader.pages, start=1):
                    if page == page_obj or (hasattr(page, "indirect_reference") and 
                                          page.indirect_reference == page_ref):
                        return idx
            except Exception:
                logger.debug("Failed to resolve field page reference", exc_info=True)
    
    return 1


def _extract_form_fields(reader: PdfReader) -> list[FormField]:
    """
    Extract all form fields from the PDF document.
    
    Tries the standard get_fields() method first, which works for most PDFs.
    Falls back to parsing page annotations if that fails, which handles
    edge cases where fields aren't in the standard AcroForm structure.
    """
    form_fields = []
    
    try:
        root_fields = reader.get_fields()
        if root_fields:
            for field_name, field_obj in root_fields.items():
                try:
                    page_num = _find_field_page(reader, field_obj)
                    
                    form_fields.append(FormField(
                        name=str(field_name),
                        field_type=_get_field_type(field_obj),
                        value=_get_field_value(field_obj),
                        required=is_field_required(field_obj),
                        page_number=page_num
                    ))
                except Exception:
                    logger.debug("Failed to parse form field from root fields", exc_info=True)
                    continue
    except Exception:
        # Fallback: extract from page annotations
        # Some PDFs store fields as widget annotations rather than AcroForm fields
        logger.debug("reader.get_fields() failed; using annotations fallback", exc_info=True)
        for page_num, page in enumerate(reader.pages, start=1):
            try:
                if "/Annots" in page:
                    annotations = page["/Annots"]
                    if annotations:
                        for annot_ref in cast(list, annotations):
                            try:
                                annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
                                if annot.get("/Subtype") == "/Widget":
                                    field_name = annot.get("/T")
                                    if field_name:
                                        # Widget annotations may have parent field objects
                                        parent = annot.get("/Parent")
                                        if parent:
                                            field_obj = parent.get_object() if hasattr(parent, "get_object") else parent
                                        else:
                                            field_obj = annot
                                        
                                        form_fields.append(FormField(
                                            name=str(field_name),
                                            field_type=_get_field_type(field_obj),
                                            value=_get_field_value(field_obj),
                                            required=is_field_required(field_obj),
                                            page_number=page_num
                                        ))
                            except Exception:
                                logger.debug("Failed to parse widget annotation on page %s", page_num, exc_info=True)
                                continue
            except Exception:
                logger.debug("Failed to process page %s annotations", page_num, exc_info=True)
                continue
    
    return form_fields


def _extract_text_regions(reader: PdfReader) -> list[TextRegion]:
    """
    Extract visible text content from all PDF pages.
    
    Used primarily for context when inferring field semantics. Text extraction
    can fail on corrupted or encrypted pages, so we skip those gracefully.
    """
    text_regions = []
    total_chars = 0

    for page_num, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text()
            if text and text.strip():
                stripped = text.strip()
                # Bound total retained/forwarded text to limit memory and
                # provider token usage on hostile or oversized documents.
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
                text_regions.append(TextRegion(
                    text=stripped,
                    page_number=page_num
                ))
        except Exception:
            logger.debug("Failed to extract text from page %s", page_num, exc_info=True)
            continue

    return text_regions


def read_pdf(pdf_path: Path, *, max_pages: Optional[int] = None) -> DocumentStructure:
    """
    Read a PDF and extract its complete structure.

    This is the main entry point for PDF introspection. Returns a structured
    representation of the document including form fields, text content, and
    metadata. No semantic inference happens here - pure extraction only.

    Args:
        pdf_path: Path to the PDF file
        max_pages: Optional maximum page count. When the document exceeds it,
            extraction is skipped and ``PdfPageLimitError`` is raised before any
            expensive text extraction runs.

    Returns:
        DocumentStructure containing metadata, form fields, and text regions

    Raises:
        FileNotFoundError: If the PDF file doesn't exist
        PdfPageLimitError: If the document exceeds ``max_pages``
    """
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
        producer=_metadata_value(metadata_dict, "/Producer")
    )
    
    form_fields = _extract_form_fields(reader)
    text_regions = _extract_text_regions(reader)
    
    return DocumentStructure(
        metadata=metadata,
        form_fields=form_fields,
        text_regions=text_regions
    )
