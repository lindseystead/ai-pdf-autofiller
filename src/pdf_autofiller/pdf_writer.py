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
from dataclasses import dataclass, field
from typing import Optional

from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, NameObject

from .acroform_fields import button_states, choice_options, collect_field_objects
from .acroform_fields import get_field_type as acroform_field_type
from .errors import UnresolvedRequiredFieldsError
from .field_utils import is_field_required
from .models import FieldMappingDecision, FillReport, MappingResult

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
        state.lstrip("/").lower(): "/" + state.lstrip("/") for state in button_states(field_obj, include_off=True)
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


@dataclass
class _WritePlan:
    """What each mapping decision resolved to, before anything is written.

    Separating the decision from the writing is what keeps both readable: this
    half is pure and easy to reason about, and the half that touches pypdf does
    one thing.
    """

    values: dict[str, str] = field(default_factory=dict)
    skipped_review: list[str] = field(default_factory=list)
    skipped_empty: list[str] = field(default_factory=list)
    skipped_invalid: list[str] = field(default_factory=list)
    skipped_required: list[str] = field(default_factory=list)


def _resolve_for_field_type(field_obj, value: str) -> Optional[str]:
    """Translate a value into the representation its field type accepts.

    Returns ``None`` when the value cannot legally go in this field, which the
    caller records as skipped rather than writing something a viewer may reject.
    """
    field_type = _field_type(field_obj)
    if field_type == "/Sig":
        # Text in a signature field cannot make a valid signature, and writing
        # it destroys any existing one.
        return None
    if field_type == "/Btn":
        return _resolve_button_value(field_obj, value)
    if field_type == "/Ch":
        return _resolve_choice_value(field_obj, value)
    return value


def _plan_writes(
    decisions: list[FieldMappingDecision], pdf_fields: dict[str, object]
) -> _WritePlan:
    """Sort mapping decisions into values to write and reasons for skipping."""
    plan = _WritePlan()

    for decision in decisions:
        name = decision.field_name
        field_obj = pdf_fields.get(name) if pdf_fields else None

        if decision.requires_review:
            plan.skipped_review.append(name)
            if field_obj is not None and is_field_required(field_obj):
                plan.skipped_required.append(name)
            continue

        if decision.selected_value is None:
            plan.skipped_empty.append(name)
            continue

        if not pdf_fields:
            # Field introspection failed entirely; let pypdf attempt the write.
            plan.values[name] = decision.selected_value
            continue

        if field_obj is None:
            # A decision for a field this document does not have.
            continue

        resolved = _resolve_for_field_type(field_obj, decision.selected_value)
        if resolved is None:
            plan.skipped_invalid.append(name)
            continue

        plan.values[name] = resolved

    return plan


def _apply_writes(writer: PdfWriter, values: dict[str, str], *, flatten: bool) -> None:
    """Write field values across the whole document in a single pass.

    Passing ``None`` lets pypdf route each value to the page its widget lives on.
    A per-page loop would re-send every value for every page — O(pages x fields)
    — and warn for each page owning none of them. ``auto_regenerate=False`` keeps
    the appearance streams pypdf just generated instead of setting
    ``/NeedAppearances`` and asking the viewer to rebuild them.
    """
    if not values:
        return

    try:
        writer.update_page_form_field_values(
            None, values, auto_regenerate=False, flatten=flatten
        )
        return
    except Exception:
        logger.debug("Document-wide field update failed; retrying per page", exc_info=True)

    for page in writer.pages:
        for name, value in values.items():
            try:
                writer.update_page_form_field_values(
                    page, {name: value}, auto_regenerate=False, flatten=flatten
                )
            except Exception:
                logger.debug("Failed to update field %r on a page", name, exc_info=True)


def _unresolved_required_fields(
    pdf_fields: dict[str, object],
    mapping_result: MappingResult,
    *,
    written: set[str],
) -> tuple[list[str], list[str]]:
    """Find required fields the fill did not satisfy.

    Checks the document itself rather than trusting the mapping result, because a
    form can require a field the mapper never saw a candidate for.
    """
    missing = list(mapping_result.missing_required)
    skipped: list[str] = []
    flagged = {d.field_name for d in mapping_result.decisions if d.requires_review}

    for name, field_obj in (pdf_fields or {}).items():
        if not is_field_required(field_obj):
            continue
        if name in written or name in missing:
            continue
        if name in flagged:
            skipped.append(name)
        else:
            missing.append(name)

    return missing, skipped


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
    # Clone document structure to preserve formatting.
    writer.clone_reader_document_root(reader)

    pdf_fields = _collect_pdf_fields(reader)
    plan = _plan_writes(mapping_result.decisions, pdf_fields)

    _apply_writes(writer, plan.values, flatten=flatten)

    missing_required, skipped_required = _unresolved_required_fields(
        pdf_fields, mapping_result, written=set(plan.values)
    )
    skipped_required = sorted(set(plan.skipped_required) | set(skipped_required))
    if missing_required or skipped_required:
        raise UnresolvedRequiredFieldsError(
            missing_fields=missing_required, skipped_fields=skipped_required
        )

    if flatten:
        _strip_form_structures(writer)

    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf_path.open("wb") as output_file:
        writer.write(output_file)

    return FillReport(
        written_fields=sorted(plan.values),
        skipped_review_fields=plan.skipped_review,
        skipped_empty_fields=plan.skipped_empty,
        skipped_invalid_fields=plan.skipped_invalid,
        flattened=flatten,
    )
