"""
Shared AcroForm field extraction helpers.

Centralizes pypdf field walking so reader and writer stay in sync when
AcroForm metadata is incomplete and widget annotations must be scanned.
"""

import logging
from typing import Literal, cast

from pypdf import PdfReader
from pypdf.generic import IndirectObject

from .field_utils import is_field_required
from .models import FormField

logger = logging.getLogger(__name__)


def resolve_object(candidate):
    """Resolve an indirect PDF reference to its target object."""
    return candidate.get_object() if hasattr(candidate, "get_object") else candidate


def get_field_type(field_obj) -> Literal["text", "button", "choice", "signature", "unknown"]:
    """Map a PDF /FT value to the internal field type label."""
    ft = field_obj.get("/FT")
    if ft == "/Tx":
        return "text"
    if ft == "/Btn":
        return "button"
    if ft == "/Ch":
        return "choice"
    if ft == "/Sig":
        return "signature"
    return "unknown"


def get_field_value(field_obj) -> str | None:
    """Read the current value from a PDF field object."""
    value = field_obj.get("/V")
    if value is None:
        return None

    if isinstance(value, (str, bool, int, float)):
        return str(value)

    if isinstance(value, IndirectObject):
        try:
            resolved = value.get_object()
            if isinstance(resolved, (str, bool, int, float)):
                return str(resolved)
        except Exception as exc:  # noqa: BLE001 - malformed refs must not abort extraction
            logger.debug("Failed to resolve indirect field value: %s", exc)

    return str(value) if value else None


def find_field_page(reader: PdfReader, field_obj) -> int:
    """Resolve the 1-based page number for a field object."""
    if not hasattr(field_obj, "get"):
        return 1

    page_ref = field_obj.get("/P")
    if not page_ref:
        return 1

    try:
        page_obj = resolve_object(page_ref)
        for idx, page in enumerate(reader.pages, start=1):
            if page == page_obj or (
                hasattr(page, "indirect_reference") and page.indirect_reference == page_ref
            ):
                return idx
    except Exception:
        logger.debug("Failed to resolve field page reference", exc_info=True)

    return 1


def collect_field_objects(reader: PdfReader) -> dict[str, object]:
    """Collect raw PDF field objects keyed by field name."""
    try:
        pdf_fields = reader.get_fields()
        if pdf_fields:
            return {str(field_name): field_obj for field_name, field_obj in pdf_fields.items()}
    except Exception:
        logger.warning(
            "Failed to read PDF form fields from AcroForm; falling back to widget annotations",
            exc_info=True,
        )

    fallback_fields: dict[str, object] = {}
    for page_num, page in enumerate(reader.pages, start=1):
        try:
            annotations = page.get("/Annots")
            if not annotations:
                continue

            for annot_ref in annotations:
                try:
                    annot = resolve_object(annot_ref)
                    if annot.get("/Subtype") != "/Widget":
                        continue

                    parent = annot.get("/Parent")
                    field_name = annot.get("/T")
                    if not field_name and parent:
                        parent_obj = resolve_object(parent)
                        field_name = parent_obj.get("/T")
                    if not field_name:
                        continue

                    field_obj = annot
                    if parent:
                        field_obj = resolve_object(parent)
                    fallback_fields.setdefault(str(field_name), field_obj)
                except Exception:
                    logger.debug(
                        "Failed to inspect widget annotation on page %s",
                        page_num,
                        exc_info=True,
                    )
        except Exception:
            logger.debug("Failed to inspect annotations on page %s", page_num, exc_info=True)

    return fallback_fields


def extract_form_fields(reader: PdfReader) -> list[FormField]:
    """Extract structured form fields from a PDF reader."""
    form_fields: list[FormField] = []

    try:
        root_fields = reader.get_fields()
        if root_fields:
            for field_name, field_obj in root_fields.items():
                try:
                    form_fields.append(
                        FormField(
                            name=str(field_name),
                            field_type=get_field_type(field_obj),
                            value=get_field_value(field_obj),
                            required=is_field_required(field_obj),
                            page_number=find_field_page(reader, field_obj),
                        )
                    )
                except Exception:
                    logger.debug(
                        "Failed to parse form field from root fields", exc_info=True
                    )
                    continue
            return form_fields
    except Exception:
        logger.debug("reader.get_fields() failed; using annotations fallback", exc_info=True)

    for page_num, page in enumerate(reader.pages, start=1):
        try:
            if "/Annots" not in page:
                continue

            annotations = page["/Annots"]
            if not annotations:
                continue

            for annot_ref in cast(list, annotations):
                try:
                    annot = resolve_object(annot_ref)
                    if annot.get("/Subtype") != "/Widget":
                        continue

                    field_name = annot.get("/T")
                    if not field_name:
                        continue

                    parent = annot.get("/Parent")
                    field_obj = resolve_object(parent) if parent else annot

                    form_fields.append(
                        FormField(
                            name=str(field_name),
                            field_type=get_field_type(field_obj),
                            value=get_field_value(field_obj),
                            required=is_field_required(field_obj),
                            page_number=page_num,
                        )
                    )
                except Exception:
                    logger.debug(
                        "Failed to parse widget annotation on page %s",
                        page_num,
                        exc_info=True,
                    )
                    continue
        except Exception:
            logger.debug(
                "Failed to process page %s annotations", page_num, exc_info=True
            )
            continue

    return form_fields
