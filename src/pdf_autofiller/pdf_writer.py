"""
PDF writer for mapped field values.

This module applies validated mapping decisions to an output PDF and enforces
required-field completion before writing.
"""

import logging
from pathlib import Path
from typing import Optional

from pypdf import PdfReader, PdfWriter

from .models import FillReport, MappingResult

logger = logging.getLogger(__name__)

# Values that toggle an AcroForm button field. Anything else is treated as an
# explicit export state (e.g. a radio-group option) and matched against the
# field's declared states.
_BUTTON_TRUTHY = {"true", "yes", "on", "1", "checked", "x", "y"}
_BUTTON_FALSY = {"false", "no", "off", "0", "unchecked", "n", ""}


class UnresolvedRequiredFieldsError(Exception):
    """
    Exception raised when required fields can't be filled.
    
    This happens when required fields are missing from user data or were
    skipped due to requires_review=True. The system won't write incomplete
    forms to avoid producing invalid documents.
    """
    
    def __init__(self, missing_fields: list[str], skipped_fields: list[str]):
        self.missing_fields = missing_fields
        self.skipped_fields = skipped_fields
        message_parts = []
        if missing_fields:
            message_parts.append(f"Missing required fields: {', '.join(missing_fields)}")
        if skipped_fields:
            message_parts.append(f"Skipped required fields (requires_review=True): {', '.join(skipped_fields)}")
        super().__init__("; ".join(message_parts))


def _collect_pdf_fields(reader: PdfReader) -> dict[str, object]:
    """Collect field metadata from AcroForm and annotation fallbacks."""
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


def _field_type(field_obj) -> Optional[str]:
    """Return the PDF field type name (e.g. '/Btn', '/Tx') if available."""
    if not hasattr(field_obj, "get"):
        return None
    try:
        ft = field_obj.get("/FT")
        return str(ft) if ft is not None else None
    except Exception:
        logger.debug("Unable to read field type from field object", exc_info=True)
        return None


def _button_states(field_obj) -> list[str]:
    """
    Return the valid state names for an AcroForm button field.

    Checkboxes and radio buttons accept a fixed set of state names (for example
    ``/Yes`` and ``/Off``). pypdf exposes these via ``/_States_`` when fields are
    read through ``get_fields()``; otherwise they can be recovered from the
    widget's normal-appearance (``/AP`` -> ``/N``) dictionary.
    """
    try:
        states = field_obj.get("/_States_")
        if states:
            return [str(state) for state in states]
    except Exception:
        logger.debug("Failed to read /_States_ from button field", exc_info=True)

    try:
        appearance = field_obj.get("/AP")
        normal = appearance.get("/N") if hasattr(appearance, "get") else None
        if normal is not None and hasattr(normal, "keys"):
            return [str(key) for key in normal.keys()]
    except Exception:
        logger.debug("Failed to read /AP states from button field", exc_info=True)

    return []


def _resolve_button_value(field_obj, value: str) -> Optional[str]:
    """
    Translate a mapped value into a valid AcroForm button state name.

    PDF button fields are only toggled when written with their exact state name,
    including the leading slash (e.g. ``/Yes``). Writing a bare ``"true"`` or
    ``"Yes"`` silently leaves the box unchecked. This normalizes boolean-style
    inputs to the field's on/off states and matches explicit export values used
    by radio groups.

    Returns the resolved state name (with leading slash), or ``None`` when the
    value cannot be mapped to a known state.
    """
    raw = value.strip()
    state_lookup = {
        state.lstrip("/").lower(): "/" + state.lstrip("/")
        for state in _button_states(field_obj)
    }
    on_states = [state for key, state in state_lookup.items() if key != "off"]
    normalized = raw.lstrip("/").lower()

    # Explicit export state (named checkbox or radio-group option).
    if normalized in state_lookup:
        return state_lookup[normalized]
    # Boolean-style truthy value -> the field's on-state (default "/Yes").
    if normalized in _BUTTON_TRUTHY:
        return on_states[0] if on_states else "/Yes"
    # Boolean-style falsy value -> off.
    if normalized in _BUTTON_FALSY:
        return "/Off"

    logger.debug(
        "Could not resolve button value %r to a known state; skipping", value
    )
    return None


def fill_pdf(
    input_pdf_path: Path,
    output_pdf_path: Path,
    mapping_result: MappingResult
) -> FillReport:
    """
    Fill PDF form fields with mapped values from mapping result.
    
    Writes values from FieldMappingDecision objects into the PDF form fields.
    Skips fields where requires_review=True or selected_value is None.
    Checkbox and radio (``/Btn``) values are translated to valid PDF state
    names so boolean inputs actually toggle the control. Preserves original
    formatting and untouched fields.

    Args:
        input_pdf_path: Path to the input PDF file
        output_pdf_path: Path where the filled PDF will be saved
        mapping_result: MappingResult containing decisions and validation info

    Returns:
        FillReport listing the fields that were written and the fields that were
        intentionally skipped (flagged for review or empty), so callers can act
        on non-required fields that were dropped instead of losing them silently.

    Raises:
        FileNotFoundError: If input PDF does not exist
        UnresolvedRequiredFieldsError: If required fields are missing or skipped
        
    Example:
        >>> from pathlib import Path
        >>> from pdf_autofiller.models import MappingResult, FieldMappingDecision
        >>> result = MappingResult(
        ...     decisions=[
        ...         FieldMappingDecision(
        ...             field_name="txtFirstName",
        ...             semantic_meaning="first_name",
        ...             selected_value="John",
        ...             confidence=0.95,
        ...             reason="Direct match",
        ...             requires_review=False
        ...         )
        ...     ],
        ...     missing_required=[],
        ...     unmapped_user_keys=[]
        ... )
        >>> fill_pdf(Path("form.pdf"), Path("filled.pdf"), result)
    """
    if not input_pdf_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf_path}")
    
    reader = PdfReader(str(input_pdf_path))
    writer = PdfWriter()
    
    # Clone document structure to preserve formatting
    writer.clone_reader_document_root(reader)
    
    pdf_fields = _collect_pdf_fields(reader)
    
    written_fields: set[str] = set()
    skipped_required_fields: list[str] = []
    skipped_review_fields: list[str] = []
    skipped_empty_fields: list[str] = []
    field_values: dict[str, str] = {}

    # Process mapping decisions.
    # Skip fields marked for review or with no value, and translate button
    # (checkbox/radio) values into valid PDF state names before writing.
    for decision in mapping_result.decisions:
        field_name = decision.field_name

        if decision.requires_review:
            skipped_review_fields.append(field_name)
            # Track required fields that were skipped
            if pdf_fields and field_name in pdf_fields:
                field_obj = pdf_fields[field_name]
                if field_obj and _is_field_required(field_obj):
                    skipped_required_fields.append(field_name)
            continue

        if decision.selected_value is None:
            skipped_empty_fields.append(field_name)
            continue

        if pdf_fields:
            if field_name not in pdf_fields:
                continue
            field_obj = pdf_fields[field_name]
            value = decision.selected_value
            if _field_type(field_obj) == "/Btn":
                resolved = _resolve_button_value(field_obj, value)
                if resolved is None:
                    # Value does not map to a valid state; leave field untouched.
                    continue
                value = resolved
            written_fields.add(field_name)
            field_values[field_name] = value
            continue

        # If field introspection failed entirely, still let pypdf attempt the write.
        written_fields.add(field_name)
        field_values[field_name] = decision.selected_value
    
    # Write field values to PDF
    # Try batch update first, fall back to individual updates if needed
    if field_values:
        for page in writer.pages:
            try:
                writer.update_page_form_field_values(page, field_values)
            except Exception:
                logger.debug("Batch field update failed on page; trying per-field writes", exc_info=True)
                # Fallback: update fields individually
                for field_name, value in field_values.items():
                    try:
                        writer.update_page_form_field_values(page, {field_name: value})
                    except Exception:
                        logger.debug(
                            "Failed to update individual field '%s' on a page",
                            field_name,
                            exc_info=True,
                        )
    
    # Validate that all required fields were filled
    missing_required = mapping_result.missing_required.copy()
    
    # Check PDF form fields for any required fields we missed
    for field_name, field_obj in (pdf_fields or {}).items():
        if _is_field_required(field_obj):
            if field_name not in written_fields and field_name not in missing_required:
                # Check if it was skipped due to review flag
                skipped_decisions = [
                    d for d in mapping_result.decisions
                    if d.field_name == field_name and d.requires_review
                ]
                if skipped_decisions:
                    if field_name not in skipped_required_fields:
                        skipped_required_fields.append(field_name)
                else:
                    missing_required.append(field_name)
    
    # Fail if required fields unresolved
    if missing_required or skipped_required_fields:
        raise UnresolvedRequiredFieldsError(
            missing_fields=missing_required,
            skipped_fields=skipped_required_fields
        )
    
    # Write output PDF
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf_path.open("wb") as output_file:
        writer.write(output_file)

    return FillReport(
        written_fields=sorted(written_fields),
        skipped_review_fields=skipped_review_fields,
        skipped_empty_fields=skipped_empty_fields,
    )


def _is_field_required(field_obj) -> bool:
    """
    Check if a PDF form field is marked as required.
    
    PDF spec uses bit flags in the /Ff field. Bit 1 (0x02) indicates
    a required field that must be filled before submission.
    """
    if not field_obj:
        return False
    
    try:
        ff = field_obj.get("/Ff", 0)
        return bool(ff & 0x02)
    except Exception:
        logger.debug("Unable to read required flag from field object", exc_info=True)
        return False
