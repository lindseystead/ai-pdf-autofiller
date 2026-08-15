"""
Shared AcroForm field extraction helpers.

Centralizes pypdf field walking so reader and writer stay in sync when
AcroForm metadata is incomplete and widget annotations must be scanned.
"""

import logging
from typing import Literal, Optional, cast

from pypdf import PdfReader
from pypdf.generic import IndirectObject

from .field_utils import is_field_required
from .models import FormField

logger = logging.getLogger(__name__)


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


def get_field_value(field_obj) -> Optional[str]:
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
        except Exception as exc:
            logger.debug("Failed to resolve indirect field value: %s", exc)

    return str(value) if value else None


def choice_options(field_obj) -> list[str]:
    """Return the permitted values for a choice field.

    ``/Opt`` entries are either a display string or a ``[export, display]`` pair;
    the export value is what must be written, so pairs are unwrapped to their
    first element.
    """
    if not hasattr(field_obj, "get"):
        return []
    try:
        raw = field_obj.get("/Opt")
        if raw is None:
            return []
        if hasattr(raw, "get_object"):
            raw = raw.get_object()
        options: list[str] = []
        for entry in raw:
            if hasattr(entry, "get_object"):
                entry = entry.get_object()
            if isinstance(entry, (list, tuple)):
                if entry:
                    options.append(str(entry[0]))
            else:
                options.append(str(entry))
        return options
    except Exception:
        logger.debug("Failed to read /Opt from choice field", exc_info=True)
        return []


def button_states(field_obj) -> list[str]:
    """Return the export states a checkbox or radio group accepts, minus /Off."""
    if not hasattr(field_obj, "get"):
        return []
    states: list[str] = []
    try:
        raw = field_obj.get("/_States_")
        if raw:
            states = [str(state) for state in raw]
    except Exception:
        logger.debug("Failed to read /_States_ from button field", exc_info=True)

    if not states:
        try:
            appearance = field_obj.get("/AP")
            normal = appearance.get("/N") if hasattr(appearance, "get") else None
            if normal is not None and hasattr(normal, "keys"):
                states = [str(key) for key in normal.keys()]
        except Exception:
            logger.debug("Failed to read /AP states from button field", exc_info=True)

    return [state for state in states if state.lstrip("/").lower() != "off"]


def field_options(field_obj) -> list[str]:
    """Return permitted values for whichever constrained field type this is."""
    kind = get_field_type(field_obj)
    if kind == "choice":
        return choice_options(field_obj)
    if kind == "button":
        return button_states(field_obj)
    return []


def find_field_page(reader: PdfReader, field_obj) -> int:
    """Resolve the 1-based page number for a field object."""
    if not hasattr(field_obj, "get"):
        return 1

    page_ref = field_obj.get("/P")
    if not page_ref:
        return 1

    try:
        page_obj = page_ref.get_object() if hasattr(page_ref, "get_object") else page_ref
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
                    annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
                    if annot.get("/Subtype") != "/Widget":
                        continue

                    parent = annot.get("/Parent")
                    field_name = annot.get("/T")
                    if not field_name and parent:
                        parent_obj = parent.get_object() if hasattr(parent, "get_object") else parent
                        field_name = parent_obj.get("/T")
                    if not field_name:
                        continue

                    field_obj = annot
                    if parent:
                        field_obj = parent.get_object() if hasattr(parent, "get_object") else parent
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
                            options=field_options(field_obj),
                        )
                    )
                except Exception:
                    logger.debug("Failed to parse form field from root fields", exc_info=True)
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
                    annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
                    if annot.get("/Subtype") != "/Widget":
                        continue

                    field_name = annot.get("/T")
                    if not field_name:
                        continue

                    parent = annot.get("/Parent")
                    if parent:
                        field_obj = parent.get_object() if hasattr(parent, "get_object") else parent
                    else:
                        field_obj = annot

                    form_fields.append(
                        FormField(
                            name=str(field_name),
                            field_type=get_field_type(field_obj),
                            value=get_field_value(field_obj),
                            required=is_field_required(field_obj),
                            page_number=page_num,
                            options=field_options(field_obj),
                        )
                    )
                except Exception:
                    logger.debug("Failed to parse widget annotation on page %s", page_num, exc_info=True)
                    continue
        except Exception:
            logger.debug("Failed to process page %s annotations", page_num, exc_info=True)
            continue

    return form_fields
