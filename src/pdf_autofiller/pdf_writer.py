"""
PDF writer for mapped field values.

This module applies validated mapping decisions to an output PDF and enforces
required-field completion before writing.

Two behaviours are worth knowing about:

*Appearances.* pypdf builds an appearance stream (``/AP``) for each field it
writes, which is what non-Acrobat viewers actually render. ``auto_regenerate``
defaults to ``True`` upstream, which additionally sets ``/NeedAppearances`` —
asking the viewer to throw those appearances away and rebuild them, and
prompting a "save changes" dialog on open. We pass ``auto_regenerate=False`` and
rely on the generated appearances.

*Flattening.* pypdf's ``flatten=True`` stamps values into page content but
leaves the AcroForm and widget annotations in place, so the result is still an
editable form. :func:`fill_pdf` strips both afterwards when asked to flatten.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject

from .acroform_fields import choice_options, collect_field_objects
from .acroform_fields import get_field_type as acroform_field_type
from .errors import UnresolvedRequiredFieldsError
from .field_utils import is_field_required
from .models import FillReport, MappingResult

logger = logging.getLogger(__name__)

__all__ = ["fill_pdf", "UnresolvedRequiredFieldsError"]

# Values that toggle an AcroForm button field. Anything else is treated as an
# explicit export state (e.g. a radio-group option) and matched against the
# field's declared states.
_BUTTON_TRUTHY = {"true", "yes", "on", "1", "checked", "x", "y"}
_BUTTON_FALSY = {"false", "no", "off", "0", "unchecked", "n", ""}


def _collect_pdf_fields(reader: PdfReader) -> dict[str, object]:
    """Collect field metadata from AcroForm and annotation fallbacks."""
    return collect_field_objects(reader)


def _field_type(field_obj) -> Optional[str]:
    """Return the PDF field type name (e.g. '/Tx', '/Btn') if available."""
    if not hasattr(field_obj, "get"):
        return None
    try:
        internal = acroform_field_type(field_obj)
        mapping = {
            "text": "/Tx",
            "button": "/Btn",
            "choice": "/Ch",
            "signature": "/Sig",
        }
        return mapping.get(internal)
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
        state.lstrip("/").lower(): "/" + state.lstrip("/") for state in _button_states(field_obj)
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

    logger.debug("Could not resolve button value %r to a known state; skipping", value)
    return None


def _resolve_choice_value(field_obj, value: str) -> Optional[str]:
    """
    Match a value against a choice field's declared options.

    Dropdowns and list boxes carry an ``/Opt`` array of permitted values. Writing
    something outside that list produces a document that viewers may show as
    blank or reject, so an unmatched value is skipped rather than written.
    Fields with no ``/Opt`` (free-text combos) accept anything.
    """
    options = choice_options(field_obj)
    if not options:
        return value

    lookup = {option.strip().lower(): option for option in options}
    matched = lookup.get(value.strip().lower())
    if matched is None:
        logger.debug(
            "Value %r is not among the choice field's %d options; skipping",
            value,
            len(options),
        )
    return matched


def _strip_form_structures(writer: PdfWriter) -> None:
    """Remove interactive form structures after values are stamped into content.

    pypdf's ``flatten`` writes the value into the page content stream but leaves
    the widgets and AcroForm behind, so the "flattened" document is still an
    editable form showing doubled text. Removing both completes the operation.
    """
    for page in writer.pages:
        annots = page.get("/Annots")
        if not annots:
            continue
        kept = []
        for annot_ref in annots:
            try:
                annot = annot_ref.get_object() if hasattr(annot_ref, "get_object") else annot_ref
                if annot.get("/Subtype") != "/Widget":
                    kept.append(annot_ref)
            except Exception:
                logger.debug("Could not inspect annotation while flattening", exc_info=True)
                kept.append(annot_ref)
        if kept:
            page[NameObject("/Annots")] = ArrayObject(kept)
        else:
            page.pop(NameObject("/Annots"), None)

    root = writer.root_object
    if "/AcroForm" in root:
        del root[NameObject("/AcroForm")]


def fill_pdf(
    input_pdf_path: Path,
    output_pdf_path: Path,
    mapping_result: MappingResult,
    *,
    flatten: bool = False,
) -> FillReport:
    """
    Fill PDF form fields with mapped values from mapping result.

    Writes values from FieldMappingDecision objects into the PDF form fields.
    Skips fields where requires_review=True or selected_value is None.
    Checkbox and radio (``/Btn``) values are translated to valid PDF state
    names so boolean inputs actually toggle the control; choice (``/Ch``) values
    are validated against the field's declared options; signature (``/Sig``)
    fields are never written. Preserves original formatting and untouched fields.

    Args:
        input_pdf_path: Path to the input PDF file
        output_pdf_path: Path where the filled PDF will be saved
        mapping_result: MappingResult containing decisions and validation info
        flatten: When True, stamp values into page content and remove the
            interactive form so the result cannot be edited downstream

    Returns:
        FillReport listing the fields that were written and the fields that were
        intentionally skipped (flagged for review, empty, or invalid for their
        field type), so callers can act on dropped fields instead of losing them
        silently.

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
    skipped_invalid_fields: list[str] = []
    field_values: dict[str, str] = {}

    # Process mapping decisions.
    # Skip fields marked for review or with no value, and translate button
    # (checkbox/radio) and choice values into valid PDF representations.
    for decision in mapping_result.decisions:
        field_name = decision.field_name

        if decision.requires_review:
            skipped_review_fields.append(field_name)
            # Track required fields that were skipped
            if pdf_fields and field_name in pdf_fields:
                field_obj = pdf_fields[field_name]
                if field_obj and is_field_required(field_obj):
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
            field_type = _field_type(field_obj)

            if field_type == "/Sig":
                # Writing to a signature field cannot produce a valid signature
                # and destroys any existing one.
                skipped_invalid_fields.append(field_name)
                continue
            if field_type == "/Btn":
                resolved = _resolve_button_value(field_obj, value)
                if resolved is None:
                    skipped_invalid_fields.append(field_name)
                    continue
                value = resolved
            elif field_type == "/Ch":
                resolved_choice = _resolve_choice_value(field_obj, value)
                if resolved_choice is None:
                    skipped_invalid_fields.append(field_name)
                    continue
                value = resolved_choice

            written_fields.add(field_name)
            field_values[field_name] = value
            continue

        # If field introspection failed entirely, still let pypdf attempt the write.
        written_fields.add(field_name)
        field_values[field_name] = decision.selected_value

    # Write field values across the whole document in a single pass.
    #
    # Passing ``None`` lets pypdf route each value to the page its widget lives
    # on. The previous per-page loop re-sent every value for every page, which
    # was O(pages x fields) and logged a warning for each page that owned none
    # of them. auto_regenerate=False keeps the appearance streams pypdf just
    # generated instead of asking the viewer to rebuild them.
    if field_values:
        try:
            writer.update_page_form_field_values(
                None, field_values, auto_regenerate=False, flatten=flatten
            )
        except Exception:
            logger.debug(
                "Document-wide field update failed; retrying per page", exc_info=True
            )
            for page in writer.pages:
                for field_name, value in field_values.items():
                    try:
                        writer.update_page_form_field_values(
                            page, {field_name: value}, auto_regenerate=False, flatten=flatten
                        )
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
        if is_field_required(field_obj):
            if field_name not in written_fields and field_name not in missing_required:
                # Check if it was skipped due to review flag
                skipped_decisions = [
                    d
                    for d in mapping_result.decisions
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
            missing_fields=missing_required, skipped_fields=skipped_required_fields
        )

    if flatten:
        _strip_form_structures(writer)

    # Write output PDF
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf_path.open("wb") as output_file:
        writer.write(output_file)

    return FillReport(
        written_fields=sorted(written_fields),
        skipped_review_fields=skipped_review_fields,
        skipped_empty_fields=skipped_empty_fields,
        skipped_invalid_fields=skipped_invalid_fields,
        flattened=flatten,
    )
