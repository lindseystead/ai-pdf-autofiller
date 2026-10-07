"""Server startup must configure logging however the app is launched.

The Dockerfile and `make run-api` start uvicorn on api_service:app directly, so
anything done only in the pdf-autofiller-api entrypoint would be skipped there.
"""

from __future__ import annotations

import importlib
import logging

from fastapi.testclient import TestClient

from pdf_autofiller.api import config

# `pdf_autofiller.api.app` the attribute is the FastAPI instance; load the module itself.
app_module = importlib.import_module("pdf_autofiller.api.app")


def _count_configure_calls(monkeypatch) -> list[None]:
    calls: list[None] = []
    monkeypatch.setattr(app_module, "configure_logging", lambda: calls.append(None))
    return calls


def test_startup_configures_logging(monkeypatch):
    calls = _count_configure_calls(monkeypatch)
    with TestClient(app_module.create_app()):  # entering runs the startup hook, as uvicorn does
        pass
    assert calls == [None]


def test_creating_the_app_without_starting_it_leaves_logging_alone(monkeypatch):
    calls = _count_configure_calls(monkeypatch)
    app_module.create_app()
    assert calls == []


def test_startup_warns_when_auth_is_on_without_a_token(monkeypatch, caplog):
    _count_configure_calls(monkeypatch)
    monkeypatch.setattr(config, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "")
    with caplog.at_level(logging.WARNING), TestClient(app_module.create_app()):
        pass
    assert any("API_AUTH_TOKEN is not set" in r.getMessage() for r in caplog.records)
