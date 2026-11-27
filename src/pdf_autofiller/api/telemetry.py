"""Opt-in, aggregate-only product events for self-hosted operators."""

from __future__ import annotations

import json
import logging
from typing import TypeAlias

from . import config

MetricValue: TypeAlias = str | int | float | bool | None

logger = logging.getLogger("pdf_autofiller.product")

ALLOWED_METRICS = frozenset(
    {
        "ai_fallback_enabled",
        "ai_inference_enabled",
        "decisions",
        "dry_run",
        "failed",
        "fields_total",
        "missing_required",
        "opaque_fields",
        "records",
        "required_fields",
        "unmapped_keys",
        "written",
    }
)
ALLOWED_EVENTS = frozenset(
    {"batch_completed", "fill_completed", "inspect_completed", "preview_completed", "template_completed"}
)


def emit_product_event(event: str, **metrics: MetricValue) -> None:
    """Emit a JSON event containing counts and feature flags only.

    The allowlist intentionally rejects field names, file names, user keys,
    values, IP addresses, and request identifiers.
    """
    if not config.PRODUCT_TELEMETRY_ENABLED:
        return
    if event not in ALLOWED_EVENTS:
        raise ValueError(f"unsafe product telemetry event: {event!r}")
    unexpected = sorted(set(metrics) - ALLOWED_METRICS)
    if unexpected:
        raise ValueError("unsafe product telemetry metric(s): " + ", ".join(unexpected))
    payload: dict[str, MetricValue] = {"event": event}
    payload.update(metrics)
    logger.info("product_event=%s", json.dumps(payload, sort_keys=True, separators=(",", ":")))
