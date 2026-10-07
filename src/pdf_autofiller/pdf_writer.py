"""
PDF writer for mapped field values.

This module applies validated mapping decisions to an output PDF and refuses to
write while required fields are unresolved, unless ``allow_partial`` is set.
"""

import logging
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

from .acroform_fields import collect_field_objects
from .errors import PdfAutofillerError
from .field_utils import is_field_required
from .models import FillReport, MappingResult

logger = logging.getLogger(__name__)


class _RedactFieldText(logging.Filter):
    """Keep field values out of pypdf's "not supported by font encoding" warning.

    pypdf passes the value as the ``text`` argument; the same condition is
    reported to callers through ``FillReport.display_warnings`` instead.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, dict) and "text" in record.args:
            record.args = {**record.args, "text": "<redacted>"}
        return True


logging.getLogger("pypdf.generic._appearance_stream").addFilter(_RedactFieldText())

# Values that toggle an AcroForm button field. Anything else is treated as an
# explicit export state (e.g. a radio-group option) and matched against the
# field's declared states.
_BUTTON_TRUTHY = {"true", "yes", "on", "1", "checked", "x", "y"}
_BUTTON_FALSY = {"false", "no", "off", "0", "unchecked", "n", ""}


class UnresolvedRequiredFieldsError(PdfAutofillerError):
    """Raised when required fields stay unresolved and ``allow_partial`` is false.

    A required field is unresolved when no user key matched it or its mapping
    was flagged ``requires_review``.
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


def _field_type(field_obj) -> str | None:
    """Return the PDF field type name (e.g. '/Btn', '/Tx') if available."""
    if not hasattr(field_obj, "get"):
        return None
    field_type = field_obj.get("/FT")
    return str(field_type) if field_type in ("/Tx", "/Btn", "/Ch", "/Sig") else None


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

    logger.debug("Button value did not match any known state; skipping")
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
    """Write ``mapping_result`` into a copy of the PDF and report what happened to every field.

    Decisions flagged ``requires_review`` or with empty values are skipped. Each
    value must satisfy its widget: checkbox/radio values become valid state
    names, choice values must match an option, text must fit ``/MaxLen``, and
    signatures are never filled. Anything that cannot be written is listed in
    ``FillReport.skipped_unwritable_fields`` with the reason.

    Args:
        flatten: Burn values into the page and remove the form fields. Values
            already in the form are kept; text the standard font cannot draw is refused.
        need_appearances: Set ``/NeedAppearances`` so viewers redraw filled values.
        allow_partial: Write even when required fields are unresolved; they are
            listed in ``FillReport.missing_required_fields``.

    Raises:
        FileNotFoundError: The input PDF does not exist.
        UnresolvedRequiredFieldsError: Required fields are unresolved and
            ``allow_partial`` is false. Nothing is written.
    """
    if not input_pdf_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf_path}")

    reader = PdfReader(str(input_pdf_path))
    writer = PdfWriter()
    writer.clone_reader_document_root(reader)  # keeps formatting and untouched fields
    pdf_fields = collect_field_objects(reader)

    skipped_review_fields: list[str] = []
    skipped_empty_fields: list[str] = []
    skipped_unwritable_fields: list[str] = []
    display_warnings: list[str] = []
    field_values: dict[str, str] = {}

    def _mark_unwritable(name: str, reason: str) -> None:
        skipped_unwritable_fields.append(f"{name} ({reason})")
        logger.warning("Unwritable mapped field %s: %s", name, reason)

    for decision in mapping_result.decisions:
        name = decision.field_name
        if decision.requires_review:
            skipped_review_fields.append(name)
            continue
        if decision.selected_value is None or not decision.selected_value.strip():
            skipped_empty_fields.append(name)
            continue
        if not pdf_fields:
            # Field introspection failed entirely; still let pypdf attempt the write.
            field_values[name] = decision.selected_value
            continue
        if name not in pdf_fields:
            _mark_unwritable(name, "missing_widget")
            continue
        value, reason, warn = _value_for_widget(pdf_fields[name], decision.selected_value, flatten=flatten)
        if value is None:
            _mark_unwritable(name, reason or "unwritable")
            continue
        if warn:
            display_warnings.append(f"{name} (font_encoding)")
        field_values[name] = value

    # pypdf flattens only the fields it is given, and flatten then removes every
    # widget, so values already in the form must be passed through or they vanish.
    write_values = {**_existing_values(pdf_fields), **field_values} if flatten else dict(field_values)
    written_fields: set[str] = set()
    if write_values:
        confirmed = _write_values(writer, write_values, need_appearances=need_appearances, flatten=flatten)
        for name in field_values:
            if name in confirmed:
                written_fields.add(name)
            else:
                _mark_unwritable(name, "write_failed")
    elif need_appearances:
        try:
            writer.set_need_appearances_writer(True)
        except Exception:
            logger.debug("Failed to set /NeedAppearances on empty write", exc_info=True)
    if flatten:
        _remove_widgets(writer)

    missing_required, skipped_required = _unresolved_required(pdf_fields, mapping_result, written_fields)
    if (missing_required or skipped_required) and not allow_partial:
        raise UnresolvedRequiredFieldsError(missing_fields=missing_required, skipped_fields=skipped_required)

    decided = {d.field_name for d in mapping_result.decisions}
    # Only terminal fields (those with a type) can hold values; containers such
    # as the ``applicant`` parent of ``applicant.firstName`` are skipped.
    unfilled_fields = [
        name
        for name, field_obj in pdf_fields.items()
        if name not in decided and _field_type(field_obj) is not None
    ]

    output_pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with output_pdf_path.open("wb") as output_file:
        writer.write(output_file)

    return FillReport(
        written_fields=sorted(written_fields),
        skipped_review_fields=skipped_review_fields,
        skipped_empty_fields=skipped_empty_fields,
        skipped_unwritable_fields=skipped_unwritable_fields,
        missing_required_fields=sorted(set(missing_required) | set(skipped_required)),
        unfilled_fields=unfilled_fields,
        display_warnings=display_warnings,
        ai_assisted_fields=sorted(
            d.field_name for d in mapping_result.decisions if d.ai_assisted and d.field_name in written_fields
        ),
    )


def _value_for_widget(field_obj, value: str, *, flatten: bool) -> tuple[str | None, str | None, bool]:
    """Apply one widget's rules to a mapped value.

    Returns ``(value_to_write, None, display_warning)``, or ``(None, reason, False)``
    when the value cannot be written to this widget.
    """
    field_type = _field_type(field_obj)
    if field_type == "/Sig":
        return None, "signature_field", False  # signatures cannot be filled programmatically
    if field_type == "/Btn":
        resolved = _resolve_button_value(field_obj, value)
        if resolved is None:
            return None, "unresolved_button_state", False
        return resolved, None, False
    if field_type == "/Tx":
        max_len = _max_length(field_obj)
        if max_len is not None and len(value) > max_len:
            return None, f"exceeds_max_length:{max_len}", False
    elif field_type == "/Ch":
        resolved_choice = _resolve_choice_value(field_obj, value)
        if resolved_choice is None:
            return None, "unresolved_choice_option", False
        value = resolved_choice
    if field_type in ("/Tx", "/Ch") and not _standard_font_can_draw(value):
        if flatten:  # would burn garbled glyphs into the page
            return None, "font_encoding", False
        return value, None, True
    return value, None, False


def _existing_values(pdf_fields: dict[str, object]) -> dict[str, str]:
    """Values already in the form (except signatures), to keep them through flatten."""
    existing: dict[str, str] = {}
    for name, field_obj in pdf_fields.items():
        value = field_obj.get("/V") if hasattr(field_obj, "get") else None
        if value and _field_type(field_obj) != "/Sig":
            existing[name] = str(value)
    return existing


def _write_values(
    writer: PdfWriter, values: dict[str, str], *, need_appearances: bool, flatten: bool
) -> set[str]:
    """Write ``values`` page by page; return the field names pypdf accepted.

    If a page rejects the batch, each field is retried alone so one bad widget
    does not block the rest. pypdf's ``auto_regenerate`` only sets
    /NeedAppearances, so viewers redraw the filled values.
    """
    confirmed: set[str] = set()
    for page in writer.pages:
        try:
            writer.update_page_form_field_values(
                page, values, auto_regenerate=need_appearances, flatten=flatten
            )
            confirmed.update(values)
        except Exception:  # pypdf raises assorted errors on malformed widgets
            logger.debug("Batch field update failed on page; trying per-field writes", exc_info=True)
            for name, value in values.items():
                try:
                    writer.update_page_form_field_values(
                        page, {name: value}, auto_regenerate=need_appearances, flatten=flatten
                    )
                    confirmed.add(name)
                except Exception:
                    logger.debug("Failed to update field '%s' on a page", name, exc_info=True)
    return confirmed


def _remove_widgets(writer: PdfWriter) -> None:
    """After flattening, drop the widgets and the AcroForm that would point at them."""
    try:
        writer.remove_annotations(subtypes="/Widget")
        # With every widget gone the AcroForm only holds dangling /Fields
        # references, which viewers flag and pypdf cannot re-read.
        writer._root_object.pop(NameObject("/AcroForm"), None)
    except Exception:
        logger.debug("Failed to remove widget annotations after flatten", exc_info=True)


def _unresolved_required(
    pdf_fields: dict[str, object], mapping_result: MappingResult, written: set[str]
) -> tuple[list[str], list[str]]:
    """Return (required fields with no value, required fields skipped for review)."""
    missing = list(mapping_result.missing_required)
    review = {d.field_name for d in mapping_result.decisions if d.requires_review}
    skipped: list[str] = []
    for name, field_obj in pdf_fields.items():
        if not is_field_required(field_obj) or name in written or name in missing:
            continue
        if name in review:
            skipped.append(name)
        else:
            missing.append(name)
    return missing, skipped
