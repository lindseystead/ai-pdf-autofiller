"""Shared helpers for PDF form field inspection."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

logger = logging.getLogger(__name__)

# UUID (with or without braces/hyphens) and long hex identifiers.
_UUID_RE = re.compile(
    r"^(?:\{?[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}\}?"
    r"|[0-9a-f]{32})$",
    re.IGNORECASE,
)
# Generic export names: field_12, Text1, txt_3, input09, ctrl-7.
_GENERIC_INDEX_RE = re.compile(
    r"^(?:field|text|txt|fld|input|ctrl|item|widget|box|edit|cell)[_-]?\d+$",
    re.IGNORECASE,
)
# Adobe LiveCycle / XFA-style path fragments that are mostly indexes.
_XFA_LEAF_RE = re.compile(r"(?:^|\.)(?:f|text|txt|field)\d+(?:\[\d+\])?$", re.IGNORECASE)


def is_field_required(field_obj) -> bool:
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


def is_opaque_field_name(name: str) -> bool:
    """
    Return True when a widget name is unlikely to match human JSON keys.

    Opaque names include UUIDs, long hex ids, generic ``field_12`` / ``Text1``
    labels, and XFA-style leaves like ``...f1_01[0]`` without readable words.
    Readable vendor exports such as ``EmployeeFirstName_AF_text`` are not opaque.
    """
    raw = (name or "").strip()
    if not raw:
        return True

    leaf = raw.split(".")[-1]
    leaf = re.sub(r"\[\d+\]$", "", leaf)
    compact = re.sub(r"[^0-9A-Za-z]", "", leaf)
    if not compact:
        return True
    if _UUID_RE.match(compact) or _UUID_RE.match(leaf.replace("{", "").replace("}", "")):
        return True
    if _GENERIC_INDEX_RE.match(leaf) or _GENERIC_INDEX_RE.match(compact):
        return True
    if _XFA_LEAF_RE.search(raw) and not re.search(r"[A-Za-z]{4,}", leaf):
        return True

    letters = sum(1 for ch in compact if ch.isalpha())
    digits = sum(1 for ch in compact if ch.isdigit())
    # Mostly numeric / hex identifiers with little readable text.
    if letters <= 2 and digits >= 4:
        return True
    if len(compact) >= 16 and re.fullmatch(r"[0-9A-Fa-f]+", compact):
        return True
    return letters == 0


def opaque_mapping_hints(
    field_names: Iterable[str],
    *,
    unmatched_opaque: Iterable[str] | None = None,
    use_semantic_inference: bool = False,
) -> list[str]:
    """Build short, actionable hints for opaque AcroForm widget names."""
    opaque = [name for name in field_names if is_opaque_field_name(name)]
    hints: list[str] = []
    if not opaque:
        return hints

    sample = ", ".join(opaque[:3])
    if len(opaque) > 3:
        sample += f", … (+{len(opaque) - 3} more)"
    hints.append(
        f"{len(opaque)} field name(s) look opaque (e.g. {sample}). "
        "Key user_data by the exact /inspect widget names, add a FORM_ALIASES_DIR pack, "
        "or enable use_semantic_inference when a provider key is configured."
    )
    unmatched = [name for name in (unmatched_opaque or []) if is_opaque_field_name(name)]
    if unmatched and not use_semantic_inference:
        hints.append(
            "Opaque fields were left unmapped with semantic inference off — "
            "re-run /preview with use_semantic_inference=true or supply exact widget keys."
        )
    return hints
