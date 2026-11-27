"""Product telemetry is opt-in and structurally unable to accept PII fields."""

import json
import logging

import pytest

from pdf_autofiller.api import config
from pdf_autofiller.api.telemetry import emit_product_event


def test_product_telemetry_is_disabled_by_default(monkeypatch, caplog):
    monkeypatch.setattr(config, "PRODUCT_TELEMETRY_ENABLED", False)
    with caplog.at_level(logging.INFO, logger="pdf_autofiller.product"):
        emit_product_event("fill_completed", fields_total=5, written=3)
    assert caplog.records == []


def test_product_telemetry_emits_machine_readable_counts(monkeypatch, caplog):
    monkeypatch.setattr(config, "PRODUCT_TELEMETRY_ENABLED", True)
    with caplog.at_level(logging.INFO, logger="pdf_autofiller.product"):
        emit_product_event(
            "fill_completed",
            fields_total=5,
            written=3,
            missing_required=1,
            ai_inference_enabled=False,
            ai_fallback_enabled=False,
        )
    message = caplog.records[-1].getMessage()
    payload = json.loads(message.removeprefix("product_event="))
    assert payload == {
        "ai_fallback_enabled": False,
        "ai_inference_enabled": False,
        "event": "fill_completed",
        "fields_total": 5,
        "missing_required": 1,
        "written": 3,
    }


@pytest.mark.parametrize("unsafe_name", ["field_name", "file_name", "user_key", "value", "ip"])
def test_product_telemetry_rejects_unapproved_dimensions(monkeypatch, unsafe_name):
    monkeypatch.setattr(config, "PRODUCT_TELEMETRY_ENABLED", True)
    with pytest.raises(ValueError, match="unsafe product telemetry"):
        emit_product_event("fill_completed", **{unsafe_name: "secret"})


def test_product_telemetry_rejects_dynamic_event_names(monkeypatch):
    monkeypatch.setattr(config, "PRODUCT_TELEMETRY_ENABLED", True)
    with pytest.raises(ValueError, match="unsafe product telemetry event"):
        emit_product_event("customer@example.com", fields_total=1)
