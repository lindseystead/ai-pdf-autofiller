"""Pytest defaults for the PDF Autofiller suite."""

from __future__ import annotations

import os

# Soft-timeout backend keeps TestClient/monkeypatch workable; production
# defaults to process isolation (hard-kill on timeout).
os.environ.setdefault("PDF_JOB_BACKEND", "thread")
