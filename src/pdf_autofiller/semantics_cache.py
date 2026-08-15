"""
In-process cache for inferred field semantics.

Semantics are a property of the *form*, not of the data being filled into it, so
inferring them again on every request pays for the same answer repeatedly. The
key is the form fingerprint (field names, types, required flags), which is stable
across re-downloads of the same document.

Deliberately in-process and bounded: a shared cache would need a store and an
invalidation story, and the win here is almost entirely within one server's
lifetime filling the same handful of forms. Nothing user-supplied is cached —
only field structure and its inferred meaning.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Optional

from .models import FieldSemantics
from .settings import get_settings

_lock = threading.Lock()
_cache: "OrderedDict[str, dict[str, FieldSemantics]]" = OrderedDict()


def get_cached_semantics(fingerprint: str) -> Optional[dict[str, FieldSemantics]]:
    """Return cached semantics for a form fingerprint, if present."""
    with _lock:
        entry = _cache.get(fingerprint)
        if entry is None:
            return None
        _cache.move_to_end(fingerprint)
        return dict(entry)


def store_cached_semantics(fingerprint: str, semantics: dict[str, FieldSemantics]) -> None:
    """Cache semantics for a form fingerprint, evicting least-recently-used."""
    max_size = get_settings().semantics_cache_size
    if max_size <= 0:
        return
    with _lock:
        _cache[fingerprint] = dict(semantics)
        _cache.move_to_end(fingerprint)
        while len(_cache) > max_size:
            _cache.popitem(last=False)


def clear_semantics_cache() -> None:
    """Drop all cached semantics."""
    with _lock:
        _cache.clear()


def cache_stats() -> dict[str, int]:
    """Return cache occupancy for health and metrics output."""
    with _lock:
        return {"entries": len(_cache)}
