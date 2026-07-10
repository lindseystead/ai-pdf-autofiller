"""Provider-call cache utilities and metrics for optional inference paths."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import FormField


@dataclass
class ProviderCacheMetrics:
    """Per-request cache metrics surfaced to API clients."""

    semantic_hits: int = 0
    semantic_misses: int = 0
    fallback_hits: int = 0
    fallback_misses: int = 0

    @property
    def total_hits(self) -> int:
        return self.semantic_hits + self.fallback_hits

    @property
    def total_misses(self) -> int:
        return self.semantic_misses + self.fallback_misses


class InMemoryProviderCache:
    """Simple thread-safe TTL cache for provider responses."""

    def __init__(self, *, ttl_seconds: int, max_entries: int):
        self._ttl_seconds = max(ttl_seconds, 1)
        self._max_entries = max(max_entries, 1)
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, tuple[float, Any]] = OrderedDict()

    def get(self, key: str) -> Any | None:
        now = time.time()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if expires_at <= now:
                self._entries.pop(key, None)
                return None
            self._entries.move_to_end(key)
            return value

    def set(self, key: str, value: Any) -> None:
        expires_at = time.time() + self._ttl_seconds
        with self._lock:
            self._entries[key] = (expires_at, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_provider_cache = InMemoryProviderCache(
    ttl_seconds=int(os.getenv("PROVIDER_CACHE_TTL_SECONDS", "900")),
    max_entries=int(os.getenv("PROVIDER_CACHE_MAX_ENTRIES", "5000")),
)


def get_provider_cache() -> InMemoryProviderCache:
    return _provider_cache


def reset_provider_cache_for_tests() -> None:
    """Clear shared cache state (used by tests)."""
    _provider_cache.clear()


def _digest_json(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def compute_form_hash(input_pdf_path: Path) -> str:
    """Return a stable SHA-256 hash for a PDF file."""
    hasher = hashlib.sha256()
    with input_pdf_path.open("rb") as handle:
        while chunk := handle.read(64 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def field_signature(field: FormField) -> str:
    """Compute a stable signature for a field's structural identity."""
    return _digest_json(
        {
            "name": field.name,
            "field_type": field.field_type,
            "required": field.required,
            "page_number": field.page_number,
        }
    )


def semantic_cache_key(*, form_hash: str, field: FormField, context_text: str | None) -> str:
    """Build semantic inference cache key."""
    return ":".join(
        [
            "semantic",
            form_hash,
            field_signature(field),
            hashlib.sha256((context_text or "").encode("utf-8")).hexdigest(),
        ]
    )


def fallback_cache_key(*, form_hash: str, field: FormField, user_data: dict[str, Any]) -> str:
    """Build fallback-mapping key using form/field identity and user-data shape."""
    user_shape = {
        "keys": sorted(user_data.keys()),
        "types": {key: type(value).__name__ for key, value in sorted(user_data.items())},
    }
    return ":".join(["fallback", form_hash, field_signature(field), _digest_json(user_shape)])
