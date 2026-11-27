"""Configuration should fail fast with actionable environment errors."""

from __future__ import annotations

import os
import subprocess
import sys


def _import_config(**environment: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(environment)
    env["PYTHONPATH"] = "src"
    return subprocess.run(
        [sys.executable, "-c", "from pdf_autofiller.api import config"],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_invalid_integer_configuration_names_the_setting():
    result = _import_config(MAX_UPLOAD_BYTES="many")
    assert result.returncode != 0
    assert "MAX_UPLOAD_BYTES must be an integer" in result.stderr


def test_non_positive_limits_are_rejected():
    result = _import_config(PDF_READ_TIMEOUT_SECONDS="0")
    assert result.returncode != 0
    assert "PDF_READ_TIMEOUT_SECONDS must be at least" in result.stderr


def test_boolean_configuration_accepts_explicit_common_values():
    for value in ("true", "false", "1", "0", "yes", "no"):
        result = _import_config(API_AUTH_ENABLED=value)
        assert result.returncode == 0, result.stderr


def test_invalid_boolean_configuration_is_not_silently_disabled():
    result = _import_config(API_AUTH_ENABLED="truthy-ish")
    assert result.returncode != 0
    assert "API_AUTH_ENABLED must be true or false" in result.stderr
