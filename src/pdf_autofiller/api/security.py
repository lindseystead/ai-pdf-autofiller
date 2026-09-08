"""Authentication and in-process rate limiting."""

from __future__ import annotations

import logging
import secrets
import time
from collections import defaultdict, deque

from fastapi import Request

from . import config
from .errors import api_error

logger = logging.getLogger(__name__)

# Per-client sliding window. Suitable for a single worker only; multi-worker
# deployments need a shared limiter at the ingress/proxy layer.
_rate_limit_state: dict[str, deque[float]] = defaultdict(deque)


def reset_rate_limit_state() -> None:
    """Clear rate-limiter state (used by tests)."""
    _rate_limit_state.clear()


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


def enforce_rate_limit(request: Request) -> None:
    """Apply a per-client sliding-window rate limit, if enabled."""
    if config.RATE_LIMIT_PER_MINUTE <= 0:
        return

    client_host = client_identifier(request)
    now = time.monotonic()
    _purge_stale_rate_limit_clients(now)
    window = _rate_limit_state[client_host]
    while window and now - window[0] >= 60.0:
        window.popleft()

    if len(window) >= config.RATE_LIMIT_PER_MINUTE:
        raise api_error(
            status_code=429,
            code="rate_limited",
            message="Too many requests",
            details={"limit_per_minute": config.RATE_LIMIT_PER_MINUTE},
            headers={"Retry-After": "60"},
        )

    window.append(now)


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
