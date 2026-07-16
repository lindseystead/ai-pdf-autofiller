"""Shared helpers for PDF form field inspection."""

import logging

logger = logging.getLogger(__name__)


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
