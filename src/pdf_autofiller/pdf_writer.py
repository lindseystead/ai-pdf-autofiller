"""
PDF writer for mapped field values.

This module applies validated mapping decisions to an output PDF and enforces
required-field completion before writing.
"""

import logging
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

from .acroform_fields import collect_field_objects
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
    state_lookup = {state.lstrip("/").lower(): "/" + state.lstrip("/") for state in _button_states(field_obj)}
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


def _max_length(field_obj) -> int | None:
    """Return a text field's ``/MaxLen`` (own or inherited), if declared.

    ``reader.get_fields()`` returns trimmed ``Field`` snapshots without
    ``/MaxLen``; the full widget dictionary is read from its source object.
    """
    node = getattr(field_obj, "indirect_reference", None) or field_obj
    if hasattr(node, "get_object"):
        node = node.get_object()
    for _ in range(32):  # bounded walk: malformed /Parent cycles must not hang
        if not hasattr(node, "get"):
            return None
        try:
            max_len = node.get("/MaxLen")
            if max_len is not None:
                return int(max_len)
            parent = node.get("/Parent")
        except Exception:
            logger.debug("Failed to read /MaxLen from field", exc_info=True)
            return None
        if parent is None:
            return None
        node = parent.get_object() if hasattr(parent, "get_object") else parent
    return None


def _standard_font_can_draw(value: str) -> bool:
    """Whether pypdf's appearance stream (standard 14 fonts, WinAnsi) can draw ``value``."""
    try:
        value.encode("cp1252")
    except UnicodeEncodeError:
        return False
    return True


def _choice_options(field_obj) -> list[tuple[str, str]]:
    """Return ``(export, display)`` pairs for a choice (``/Ch``) field.

    ``/Opt`` entries are either a plain string (export and display are the same)
    or an ``[export, display]`` array, as used by most state/country dropdowns.
    """
    # pypdf's get_fields() mirrors /Opt into /_States_; use it only if /Opt is absent.
    opt = field_obj.get("/Opt") or field_obj.get("/_States_")
    opt = opt.get_object() if hasattr(opt, "get_object") else opt
    options: list[tuple[str, str]] = []
    for entry in opt if isinstance(opt, list) else []:  # malformed /Opt: no options
        entry = entry.get_object() if hasattr(entry, "get_object") else entry
        if isinstance(entry, list) and entry:
            options.append((str(entry[0]), str(entry[-1])))
        else:
            name = str(entry).lstrip("/")
            options.append((name, name))
    return list(dict.fromkeys(options))


def _resolve_choice_value(field_obj, value: str) -> str | None:
    """
    Resolve a mapped value for a choice (``/Ch``) field to its export value.

    Writes the value as-is when no options are declared. Otherwise the value
    must match an option's export or display text (case-insensitive); unmatched
    values return ``None`` so callers report them as unwritable instead of
    writing an invalid option.
    """
    raw = value.strip()
    options = _choice_options(field_obj)
    if not options:
        return raw

    wanted = raw.lstrip("/").lower()
    for export, display in options:
        if wanted in (export.lstrip("/").lower(), display.lower()):
            return export
    logger.debug("Choice value did not match any declared option; skipping")
    return None


def fill_pdf(
    input_pdf_path: Path,
    output_pdf_path: Path,
    mapping_result: MappingResult,
    *,
    flatten: bool = False,
    need_appearances: bool = True,
    allow_partial: bool = False,
) -> FillReport:
    """
    Fill PDF form fields with mapped values from mapping result.

    Writes values from FieldMappingDecision objects into the PDF form fields.
    Skips fields where requires_review=True or selected_value is None.
    Checkbox and radio (``/Btn``) values are translated to valid PDF state
    names so boolean inputs actually toggle the control. Choice (``/Ch``)
    fields must match ``/Opt`` / ``/_States_`` when those are present;
    otherwise the value is written as-is. Signature (``/Sig``) fields are
    never filled. Preserves original
    formatting and untouched fields unless ``flatten=True``.

    Args:
        input_pdf_path: Path to the input PDF file
        output_pdf_path: Path where the filled PDF will be saved
        mapping_result: MappingResult containing decisions and validation info
        flatten: When true, burn field appearances into page content and remove
            widget annotations (archival / non-editable output)
        need_appearances: When true (default), set AcroForm ``/NeedAppearances``
            so PDF viewers regenerate visible field appearances from ``/V``.
            pypdf's ``auto_regenerate`` flag only toggles this bit — it does not
            embed new appearance streams.
        allow_partial: When true, unresolved required fields do not abort the
            write; they are listed in ``FillReport.missing_required_fields``
            so callers still get a usable document plus a to-do list.

    Returns:
        FillReport listing the fields that were written and the fields that were
        intentionally skipped (flagged for review or empty), so callers can act
        on non-required fields that were dropped instead of losing them silently.

    Raises:
        FileNotFoundError: If input PDF does not exist
        UnresolvedRequiredFieldsError: If required fields are missing or skipped
            and ``allow_partial`` is false

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
    skipped_unwritable_fields: list[str] = []
    field_values: dict[str, str] = {}

    display_warnings: list[str] = []

    def _mark_unwritable(name: str, reason: str) -> None:
        skipped_unwritable_fields.append(f"{name} ({reason})")
        logger.warning("Unwritable mapped field %s: %s", name, reason)

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
                if field_obj and is_field_required(field_obj):
                    skipped_required_fields.append(field_name)
            continue

        if decision.selected_value is None:
            skipped_empty_fields.append(field_name)
            continue

        if pdf_fields:
            if field_name not in pdf_fields:
                _mark_unwritable(field_name, "missing_widget")
                continue
            field_obj = pdf_fields[field_name]
            field_ft = _field_type(field_obj)
            # Signature widgets cannot be programmatically filled.
            if field_ft == "/Sig":
                _mark_unwritable(field_name, "signature_field")
                continue
            value = decision.selected_value
            if field_ft == "/Btn":
                resolved = _resolve_button_value(field_obj, value)
                if resolved is None:
                    _mark_unwritable(field_name, "unresolved_button_state")
                    continue
                value = resolved
            elif field_ft == "/Tx":
                max_len = _max_length(field_obj)
                if max_len is not None and len(value) > max_len:
                    _mark_unwritable(field_name, f"exceeds_max_length:{max_len}")
                    continue
            elif field_ft == "/Ch":
                resolved_choice = _resolve_choice_value(field_obj, value)
                if resolved_choice is None:
                    _mark_unwritable(field_name, "unresolved_choice_option")
                    continue
                value = resolved_choice
            if field_ft in ("/Tx", "/Ch") and not _standard_font_can_draw(value):
                if flatten:  # would burn garbled glyphs into the page
                    _mark_unwritable(field_name, "font_encoding")
                    continue
                display_warnings.append(f"{field_name} (font_encoding)")
            field_values[field_name] = value
            continue

        # If field introspection failed entirely, still let pypdf attempt the write.
        field_values[field_name] = decision.selected_value

    # Write field values to PDF. Only fields with at least one successful
    # update_page_form_field_values call are reported as written — failures
    # are never silently counted as success.
    # pypdf's auto_regenerate only sets /NeedAppearances (viewer regenerates
    # visible glyphs). Default True so filled /V values show in common viewers.
    # pypdf flattens only the fields it is given, and flatten then removes every
    # widget, so values already in the form must be passed through or they vanish.
    write_values = dict(field_values)
    if flatten:
        for field_name, field_obj in (pdf_fields or {}).items():
            existing = field_obj.get("/V") if hasattr(field_obj, "get") else None
            if field_name not in write_values and existing and _field_type(field_obj) != "/Sig":
                write_values[field_name] = str(existing)

    if write_values:
        confirmed_writes: set[str] = set()
        for page in writer.pages:
            try:
                writer.update_page_form_field_values(
                    page,
                    write_values,
                    auto_regenerate=need_appearances,
                    flatten=flatten,
                )
                confirmed_writes.update(write_values.keys())
            except Exception:
                logger.debug(
                    "Batch field update failed on page; trying per-field writes",
                    exc_info=True,
                )
                for field_name, value in write_values.items():
                    try:
                        writer.update_page_form_field_values(
                            page,
                            {field_name: value},
                            auto_regenerate=need_appearances,
                            flatten=flatten,
                        )
                        confirmed_writes.add(field_name)
                    except Exception:
                        logger.debug(
                            "Failed to update individual field '%s' on a page",
                            field_name,
                            exc_info=True,
                        )

        for field_name in field_values:
            if field_name in confirmed_writes:
                written_fields.add(field_name)
            else:
                _mark_unwritable(field_name, "write_failed")
    elif need_appearances:
        try:
            writer.set_need_appearances_writer(True)
        except Exception:
            logger.debug("Failed to set /NeedAppearances on empty write", exc_info=True)

    if flatten:
        try:
            writer.remove_annotations(subtypes="/Widget")
            # With every widget gone the AcroForm only holds dangling /Fields
            # references, which viewers flag and pypdf cannot re-read.
            writer._root_object.pop(NameObject("/AcroForm"), None)
        except Exception:
            logger.debug("Failed to remove widget annotations after flatten", exc_info=True)

    # Validate that all required fields were filled
    missing_required = mapping_result.missing_required.copy()

    # Check PDF form fields for any required fields we missed
    for field_name, field_obj in (pdf_fields or {}).items():
        if not is_field_required(field_obj):
            continue
        if field_name in written_fields or field_name in missing_required:
            continue
        # Check if it was skipped due to review flag
        skipped_decisions = [
            d for d in mapping_result.decisions if d.field_name == field_name and d.requires_review
        ]
        if skipped_decisions:
            if field_name not in skipped_required_fields:
                skipped_required_fields.append(field_name)
        else:
            missing_required.append(field_name)

    if (missing_required or skipped_required_fields) and not allow_partial:
        raise UnresolvedRequiredFieldsError(
            missing_fields=missing_required, skipped_fields=skipped_required_fields
        )

    decided = {d.field_name for d in mapping_result.decisions}
    # Only terminal fields (those with a type) can hold values; containers
    # such as the ``applicant`` parent of ``applicant.firstName`` are skipped.
    unfilled_fields = [
        name
        for name, field_obj in (pdf_fields or {}).items()
        if name not in decided and _field_type(field_obj) is not None
    ]

    # Write output PDF
    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf_path.open("wb") as output_file:
        writer.write(output_file)

    return FillReport(
        written_fields=sorted(written_fields),
        skipped_review_fields=skipped_review_fields,
        skipped_empty_fields=skipped_empty_fields,
        skipped_unwritable_fields=skipped_unwritable_fields,
        missing_required_fields=sorted(set(missing_required) | set(skipped_required_fields)),
        unfilled_fields=unfilled_fields,
        display_warnings=display_warnings,
    )
