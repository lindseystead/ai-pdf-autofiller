"""Authentication and rate limiting (in-process or shared file)."""

from __future__ import annotations

import fcntl
import json
import logging
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import HTTPException, Request

from . import config
from .errors import api_error

logger = logging.getLogger(__name__)

# Per-client sliding window for the memory backend (single worker).
_rate_limit_state: dict[str, deque[float]] = defaultdict(deque)


def reset_rate_limit_state() -> None:
    """Clear in-memory rate-limiter state and truncate a file store if configured."""
    _rate_limit_state.clear()
    if config.RATE_LIMIT_BACKEND == "file":
        path = Path(config.RATE_LIMIT_STORE_PATH)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
        except OSError:
            logger.debug("Unable to reset rate-limit file store at %s", path, exc_info=True)


def rate_limit_health_status() -> str:
    """Health-check label for the active rate-limit backend."""
    if config.RATE_LIMIT_PER_MINUTE <= 0:
        return "disabled"
    if config.RATE_LIMIT_BACKEND == "file":
        return "shared_file"
    return "in_process"


def client_identifier(request: Request) -> str:
    """Resolve the client key used for rate limiting."""
    if config.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _purge_stale_rate_limit_clients(now: float) -> None:
    """Drop idle client buckets to bound memory use under rotating clients."""
    if len(_rate_limit_state) <= 1000:
        return
    stale_clients = [
        client_id
        for client_id, window in _rate_limit_state.items()
        if not window or now - window[-1] >= 60.0
    ]
    for client_id in stale_clients:
        _rate_limit_state.pop(client_id, None)


def _enforce_memory_rate_limit(client_host: str, now: float) -> None:
    _purge_stale_rate_limit_clients(now)
    window = _rate_limit_state[client_host]
    while window and now - window[0] >= 60.0:
        window.popleft()

    if len(window) >= config.RATE_LIMIT_PER_MINUTE:
        raise api_error(
            status_code=429,
            code="rate_limited",
            message="Too many requests",
            details={
                "limit_per_minute": config.RATE_LIMIT_PER_MINUTE,
                "backend": "memory",
            },
            headers={"Retry-After": "60"},
        )

    window.append(now)


def _enforce_file_rate_limit(client_host: str, now: float) -> None:
    """Sliding-window limiter shared across workers on the same host via flock."""
    path = Path(config.RATE_LIMIT_STORE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)

    with path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.seek(0)
            raw = handle.read().strip()
            try:
                payload = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                logger.warning("Corrupt rate-limit store at %s; resetting", path)
                payload = {}
            if not isinstance(payload, dict):
                payload = {}

            window = [
                float(ts)
                for ts in payload.get(client_host, [])
                if isinstance(ts, (int, float)) and now - float(ts) < 60.0
            ]
            if len(window) >= config.RATE_LIMIT_PER_MINUTE:
                raise api_error(
                    status_code=429,
                    code="rate_limited",
                    message="Too many requests",
                    details={
                        "limit_per_minute": config.RATE_LIMIT_PER_MINUTE,
                        "backend": "file",
                    },
                    headers={"Retry-After": "60"},
                )

            window.append(now)
            payload[client_host] = window

            pruned = {
                key: [float(ts) for ts in stamps if now - float(ts) < 60.0]
                for key, stamps in payload.items()
                if isinstance(stamps, list)
            }
            pruned = {key: stamps for key, stamps in pruned.items() if stamps}
            if len(pruned) > 5000:
                ranked = sorted(
                    pruned.items(),
                    key=lambda item: item[1][-1] if item[1] else 0.0,
                    reverse=True,
                )
                pruned = dict(ranked[:5000])

            handle.seek(0)
            handle.truncate()
            json.dump(pruned, handle)
            handle.flush()
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def enforce_rate_limit(request: Request) -> None:
    """Apply a per-client sliding-window rate limit, if enabled."""
    if config.RATE_LIMIT_PER_MINUTE <= 0:
        return

    client_host = client_identifier(request)
    # Wall-clock time so file-backed windows are comparable across processes.
    now = time.time() if config.RATE_LIMIT_BACKEND == "file" else time.monotonic()

    if config.RATE_LIMIT_BACKEND == "file":
        try:
            _enforce_file_rate_limit(client_host, now)
            return
        except HTTPException:
            raise
        except OSError:
            logger.warning(
                "File rate-limit backend unavailable at %s; falling back to in-process",
                config.RATE_LIMIT_STORE_PATH,
                exc_info=True,
            )
            now = time.monotonic()

    _enforce_memory_rate_limit(client_host, now)


def require_api_key(request: Request) -> None:
    """Validate API key auth when enabled."""
    if not config.API_AUTH_ENABLED:
        return

    if not config.API_AUTH_TOKEN:
        logger.error("API_AUTH_ENABLED is true but API_AUTH_TOKEN is not configured")
        raise api_error(
            status_code=500,
            code="server_auth_config_error",
            message="Server authentication configuration error",
        )

    incoming_token = request.headers.get(config.API_KEY_HEADER)
    if incoming_token is None or not secrets.compare_digest(
        incoming_token, config.API_AUTH_TOKEN
    ):
        raise api_error(
            status_code=401,
            code="unauthorized",
            message="Unauthorized",
        )


def guard_mutating_request(request: Request) -> None:
    """Auth first, then rate-limit — unauthenticated scans must not burn quota."""
    require_api_key(request)
    enforce_rate_limit(request)
