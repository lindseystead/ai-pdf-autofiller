"""Process configuration loaded from environment variables."""

from __future__ import annotations

import logging
import os
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    raise RuntimeError(f"{name} must be true or false, got {raw!r}")


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}, got {value}")
    return value


def _env_float(name: str, default: float, *, minimum: float = 0.1) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number, got {raw!r}") from exc
    if value < minimum:
        raise RuntimeError(f"{name} must be at least {minimum}, got {value}")
    return value


LOG_LEVEL_NAME = os.getenv("LOG_LEVEL", "INFO").upper()
# Optional structured JSON logs for aggregators (LOG_FORMAT=json).
LOG_FORMAT = os.getenv("LOG_FORMAT", "text").lower()
# Fail closed: authentication is enabled unless explicitly disabled.
API_AUTH_ENABLED = _env_bool("API_AUTH_ENABLED", True)
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "")
API_KEY_HEADER = os.getenv("API_KEY_HEADER", "X-API-Key")
MAX_UPLOAD_BYTES = _env_int("MAX_UPLOAD_BYTES", 5 * 1024 * 1024)
# Bound the aggregate binary payload returned by /batch. Base64 adds roughly
# one third on the wire, so this limit is checked against the source PDF bytes
# before the response object is assembled in memory.
BATCH_MAX_RESPONSE_BYTES = _env_int("BATCH_MAX_RESPONSE_BYTES", 25 * 1024 * 1024)
# Room in a request body for the multipart envelope and the user_data part on
# top of the PDF itself; requests larger than MAX_UPLOAD_BYTES + this are cut off.
FORM_OVERHEAD_BYTES = 1024 * 1024
# JSON-only product mutations never need to carry PDF bytes. Reject oversized
# bodies before FastAPI parses them, just like multipart uploads.
JSON_BODY_MAX_BYTES = _env_int("JSON_BODY_MAX_BYTES", 1024 * 1024)
MAX_PDF_PAGES = _env_int("MAX_PDF_PAGES", 200)
# Wall-clock budget for full pipeline processing on /fill, /preview, and /inspect.
PDF_READ_TIMEOUT_SECONDS = _env_float("PDF_READ_TIMEOUT_SECONDS", 20)
RATE_LIMIT_PER_MINUTE = _env_int("RATE_LIMIT_PER_MINUTE", 60)
# memory = per-process (default). file = flock-backed store shared by workers on one host.
RATE_LIMIT_BACKEND = os.getenv("RATE_LIMIT_BACKEND", "memory").strip().lower()
if RATE_LIMIT_BACKEND not in {"memory", "file"}:
    RATE_LIMIT_BACKEND = "memory"
RATE_LIMIT_STORE_PATH = os.getenv(
    "RATE_LIMIT_STORE_PATH",
    "/tmp/pdf-autofiller-rate-limit.json",
)
TRUST_PROXY_HEADERS = _env_bool("TRUST_PROXY_HEADERS", False)
PRODUCT_TELEMETRY_ENABLED = _env_bool("PRODUCT_TELEMETRY_ENABLED", False)
# Durable self-hosted template metadata and PDF objects. Mount this directory
# on persistent storage in containers; permissions are restricted on creation.
PRODUCT_DATA_DIR = Path(os.getenv("PRODUCT_DATA_DIR", "./pdf-autofiller-data"))
# Number of reverse proxies in front of the app that append to X-Forwarded-For.
# The client IP is the entry that many hops from the right; anything further
# left is client-supplied and must not be trusted (it would let callers rotate
# fake IPs to evade the rate limit).
TRUSTED_PROXY_COUNT = _env_int("TRUSTED_PROXY_COUNT", 1)
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
