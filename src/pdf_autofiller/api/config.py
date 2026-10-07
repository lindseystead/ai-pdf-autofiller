"""Process configuration loaded from environment variables."""

from __future__ import annotations

import logging
import os
from pathlib import Path

LOG_LEVEL_NAME = os.getenv("LOG_LEVEL", "INFO").upper()
# Optional structured JSON logs for aggregators (LOG_FORMAT=json).
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").lower()
# Fail closed: authentication is enabled unless explicitly disabled.
API_AUTH_ENABLED = os.getenv("API_AUTH_ENABLED", "true").lower() == "true"
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")
API_KEY_HEADER = os.getenv("API_KEY_HEADER", "X-API-Key")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))
# Room in a request body for the multipart envelope and the user_data part on
# top of the PDF itself; requests larger than MAX_UPLOAD_BYTES + this are cut off.
FORM_OVERHEAD_BYTES = 1024 * 1024
MAX_PDF_PAGES = int(os.getenv("MAX_PDF_PAGES", "200"))
# Wall-clock budget for full pipeline processing on /fill, /preview, and /inspect.
PDF_READ_TIMEOUT_SECONDS = float(os.getenv("PDF_READ_TIMEOUT_SECONDS", "20"))
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", "60"))
# memory = per-process (default). file = flock-backed store shared by workers on one host.
RATE_LIMIT_BACKEND = os.getenv("RATE_LIMIT_BACKEND", "memory").strip().lower()
if RATE_LIMIT_BACKEND not in {"memory", "file"}:
    RATE_LIMIT_BACKEND = "memory"
RATE_LIMIT_STORE_PATH = os.getenv(
    "RATE_LIMIT_STORE_PATH",
    "/tmp/pdf-autofiller-rate-limit.json",
)
TRUST_PROXY_HEADERS = os.getenv("TRUST_PROXY_HEADERS", "false").lower() == "true"
# Number of reverse proxies in front of the app that append to X-Forwarded-For.
# The client IP is the entry that many hops from the right; anything further
# left is client-supplied and must not be trusted (it would let callers rotate
# fake IPs to evade the rate limit).
TRUSTED_PROXY_COUNT = max(1, int(os.getenv("TRUSTED_PROXY_COUNT", "1")))
UPLOAD_CHUNK_BYTES = 64 * 1024

_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = _PACKAGE_ROOT.parents[1]
SAMPLE_CANDIDATES = (
    _REPO_ROOT / "samples" / "sample_form.pdf",
    Path("/app/samples/sample_form.pdf"),
)


def resolve_log_level() -> int:
    """Resolve the configured log level without mutating global logging state."""
    level = getattr(logging, LOG_LEVEL_NAME, None)
    if not isinstance(level, int):
        return logging.INFO
    return level
