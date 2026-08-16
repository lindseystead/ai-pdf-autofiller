"""
PDF writer for mapped field values.

This module applies validated mapping decisions to an output PDF and enforces
required-field completion before writing.

Writes are **verified**: after the output is produced it is re-read and each
intended value is confirmed present. The PDF libraries involved can decline a
write without raising, so reporting a field as written purely because a write
was attempted would let a silently incomplete document look complete.
"""

import logging
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from .acroform_fields import collect_field_objects, get_field_value
from .acroform_fields import get_field_type as acroform_field_type
from .field_utils import is_field_required
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

    This happens when required fields are missing from user data, were skipped
    due to requires_review=True, or could not be verified in the written output.
    The system won't report an incomplete form as complete.
    """

    def __init__(self, missing_fields: list[str], skipped_fields: list[str]):
        self.missing_fields = missing_fields
        self.skipped_fields = skipped_fields
        message_parts = []
        if missing_fields:
            message_parts.append(f"Missing required fields: {', '.join(missing_fields)}")
        if skipped_fields:
            message_parts.append(
                f"Skipped required fields (requires_review=True): {', '.join(skipped_fields)}"
            )
        super().__init__("; ".join(message_parts))


def _collect_pdf_fields(reader: PdfReader) -> dict[str, object]:
    """Collect field metadata from AcroForm and annotation fallbacks."""
    return collect_field_objects(reader)


def _field_type(field_obj) -> str | None:
    """Return the PDF field type name (e.g. '/Btn', '/Tx') if available."""
    if not hasattr(field_obj, "get"):
        return None
    try:
        internal = acroform_field_type(field_obj)
    except Exception:
        logger.debug("Unable to read field type from field object", exc_info=True)
        return None
    return {
        "text": "/Tx",
        "button": "/Btn",
        "choice": "/Ch",
        "signature": "/Sig",
    }.get(internal)


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
            return [str(key) for key in normal]
    except Exception:
        logger.debug("Failed to read /AP states from button field", exc_info=True)

    return []


def _resolve_button_value(field_obj, value: str) -> str | None:
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

    logger.debug("Could not resolve button value %r to a known state; skipping", value)
    return None


def _values_match(expected: str, actual: str | None) -> bool:
    """Compare an intended value with what the output document actually holds."""
    if actual is None:
        return False
    if actual == expected:
        return True
    # Button states round-trip as PDF names ("/Yes"); compare leniently.
    return actual.strip().lstrip("/").casefold() == expected.strip().lstrip("/").casefold()


def _verify_written_values(
    output_pdf_path: Path, intended: dict[str, str]
) -> tuple[list[str], list[str]]:
    """
    Re-read the output document and confirm each intended value landed.

    Returns:
        Tuple of (verified_field_names, unverified_field_names)

    Verification fails closed. If the output cannot be re-read or exposes no
    fields, nothing can be confirmed, so every intended field is reported as
    unverified rather than assumed written — otherwise ``written_fields`` would
    claim a confirmation the service never actually obtained.
    """
    if not intended:
        return [], []

    try:
        output_fields = _collect_pdf_fields(PdfReader(str(output_pdf_path)))
    except Exception:
        logger.warning(
            "Could not re-read output PDF to verify written fields", exc_info=True
        )
        return [], sorted(intended)

    if not output_fields:
        logger.warning("Output PDF exposed no form fields; cannot verify writes")
        return [], sorted(intended)

    verified: list[str] = []
    unverified: list[str] = []
    for field_name, expected in intended.items():
        field_obj = output_fields.get(field_name)
        actual = None
        if field_obj is not None:
            try:
                actual = get_field_value(field_obj)
            except Exception:
                logger.debug(
                    "Failed to read back value for field '%s'", field_name, exc_info=True
                )
        if _values_match(expected, actual):
            verified.append(field_name)
        else:
            logger.warning(
                "Field '%s' was written but could not be verified in the output PDF",
                field_name,
            )
            unverified.append(field_name)

    return sorted(verified), sorted(unverified)


def fill_pdf(
    input_pdf_path: Path, output_pdf_path: Path, mapping_result: MappingResult
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
        FillReport listing the fields verified in the output, the fields whose
        writes could not be verified, and the fields that were intentionally
        skipped (flagged for review or empty).

    Raises:
        FileNotFoundError: If input PDF does not exist
        UnresolvedRequiredFieldsError: If required fields are missing, skipped,
            or could not be verified in the output. The output file may exist in
            that case; it is not a complete document and should be discarded.

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
        ...             requires_review=False,
        ...         )
        ...     ],
        ...     missing_required=[],
        ...     unmapped_user_keys=[],
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
            field_obj = pdf_fields.get(field_name) if pdf_fields else None
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
            if _field_type(field_obj) == "/Btn":
                resolved = _resolve_button_value(field_obj, value)
                if resolved is None:
                    # Value does not map to a valid state; leave field untouched.
                    continue
                value = resolved
            field_values[field_name] = value
            continue

        # If field introspection failed entirely, still let pypdf attempt the write.
        field_values[field_name] = decision.selected_value

    # Validate that all required fields can be filled before producing output.
    missing_required = mapping_result.missing_required.copy()
    for field_name, field_obj in (pdf_fields or {}).items():
        if not is_field_required(field_obj) or field_name in field_values:
            continue
        if field_name in missing_required:
            continue
        was_skipped_for_review = any(
            decision.field_name == field_name and decision.requires_review
            for decision in mapping_result.decisions
        )
        if was_skipped_for_review:
            if field_name not in skipped_required_fields:
                skipped_required_fields.append(field_name)
        else:
            missing_required.append(field_name)

    if missing_required or skipped_required_fields:
        raise UnresolvedRequiredFieldsError(
            missing_fields=missing_required, skipped_fields=skipped_required_fields
        )

    # Write field values to PDF.
    # Try batch update first, fall back to individual updates if needed.
    if field_values:
        for page in writer.pages:
            try:
                writer.update_page_form_field_values(page, field_values)
            except Exception:
                logger.debug(
                    "Batch field update failed on page; trying per-field writes",
                    exc_info=True,
                )
                for field_name, value in field_values.items():
                    try:
                        writer.update_page_form_field_values(page, {field_name: value})
                    except Exception:
                        logger.debug(
                            "Failed to update individual field '%s' on a page",
                            field_name,
                            exc_info=True,
                        )

    # Write output PDF
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf_path.open("wb") as output_file:
        writer.write(output_file)

    written_fields, failed_fields = _verify_written_values(output_pdf_path, field_values)

    # A required field that did not survive the write is not a complete document.
    # Boundary of this guarantee: required-ness is read from the input document's
    # form structure. When that introspection returned nothing, the writer wrote
    # blind and cannot tell which fields were required, so unverified fields are
    # reported in failed_fields rather than raising a claim it cannot support.
    # Required fields that could not be *mapped* were already rejected above.
    unverified_required = [
        field_name
        for field_name in failed_fields
        if pdf_fields and is_field_required(pdf_fields.get(field_name))
    ]
    if unverified_required:
        raise UnresolvedRequiredFieldsError(
            missing_fields=unverified_required, skipped_fields=[]
        )

    return FillReport(
        written_fields=written_fields,
        failed_fields=failed_fields,
        skipped_review_fields=skipped_review_fields,
        skipped_empty_fields=skipped_empty_fields,
    )
