"""Server startup must configure logging however the app is launched.

The Dockerfile and `make run-api` start uvicorn on api_service:app directly, so
anything done only in the pdf-autofiller-api entrypoint would be skipped there.
"""

from __future__ import annotations

import importlib
import logging

import pytest
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


def test_console_script_binds_loopback_unless_api_host_is_set(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run(app_path: str, **kwargs: object) -> None:
        captured["app"] = app_path
        captured.update(kwargs)

    monkeypatch.delenv("API_HOST", raising=False)
    monkeypatch.delenv("API_PORT", raising=False)
    monkeypatch.setattr("uvicorn.run", fake_run)
    app_module.run()
    assert captured["app"] == "pdf_autofiller.api_service:app"
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8000

    monkeypatch.setenv("API_HOST", "0.0.0.0")
    monkeypatch.setenv("API_PORT", "9000")
    app_module.run()
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 9000


def test_console_script_rejects_a_bad_port(monkeypatch):
    monkeypatch.setenv("API_PORT", "nope")
    with pytest.raises(SystemExit, match="API_PORT"):
        app_module.run()


def test_startup_warns_when_auth_is_on_without_a_token(monkeypatch, caplog):
    _count_configure_calls(monkeypatch)
    monkeypatch.setattr(config, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "")
    with caplog.at_level(logging.WARNING), TestClient(app_module.create_app()):
        pass
    assert any("API_AUTH_TOKEN is not set" in r.getMessage() for r in caplog.records)
