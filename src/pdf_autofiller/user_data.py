"""
User-data normalization applied before mapping.

Callers often send nested JSON (``{"applicant": {"firstName": "Jane"}}``)
while AcroForm exports use hierarchical names (``applicant.firstName``).
Flattening nested objects into dotted paths lets both line up, and a unique
leaf key (``firstName``) is also offered to alias matching.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# Deeper payloads are rejected: they are never legitimate form data and can
# exhaust the interpreter stack when serialized to worker processes.
MAX_USER_DATA_DEPTH = int(os.getenv("MAX_USER_DATA_DEPTH", "16"))


class UserDataTooDeepError(ValueError):
    """Raised when user data nests deeper than ``MAX_USER_DATA_DEPTH``."""

    def __init__(self, max_depth: int):
        self.max_depth = max_depth
        super().__init__(f"user_data nests deeper than the limit of {max_depth}")


def validate_user_data_depth(data: Any, max_depth: int = MAX_USER_DATA_DEPTH) -> None:
    """Reject containers nested deeper than ``max_depth`` (iterative, stack-safe)."""
    stack: list[tuple[Any, int]] = [(data, 1)]
    while stack:
        value, depth = stack.pop()
        children: list[Any]
        if isinstance(value, dict):
            children = list(value.values())
        elif isinstance(value, list):
            children = value
        else:
            continue
        if depth > max_depth:
            raise UserDataTooDeepError(max_depth)
        stack.extend((child, depth + 1) for child in children)


@dataclass
class FlatUserData:
    """Flattened user data plus unique-leaf aliases for nested keys."""

    values: dict[str, Any] = field(default_factory=dict)
    leaf_aliases: dict[str, str] = field(default_factory=dict)

    def candidates(self) -> dict[str, Any]:
        """Keys offered to matching: full paths first, then unique leaves."""
        merged = dict(self.values)
        for leaf, path in self.leaf_aliases.items():
            merged.setdefault(leaf, self.values[path])
        return merged

    def source_key(self, key: str) -> str:
        """Resolve a matched candidate key back to its full path."""
        return key if key in self.values else self.leaf_aliases.get(key, key)


def flatten_user_data(data: dict[str, Any], max_depth: int = MAX_USER_DATA_DEPTH) -> FlatUserData:
    """Flatten nested dicts/lists into dotted paths (``a.b``, ``items.0``)."""
    if not isinstance(data, dict):
        raise TypeError(f"user_data must be a dict (JSON object), got {type(data).__name__}")
    validate_user_data_depth(data, max_depth)
    values: dict[str, Any] = {}

    def _walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict) and value:
            for key, child in value.items():
                _walk(f"{prefix}.{key}" if prefix else str(key), child)
        elif isinstance(value, list) and value:
            for index, child in enumerate(value):
                _walk(f"{prefix}.{index}", child)
        else:
            # Empty containers carry no value; never stringify them into "[]"/"{}".
            values[prefix] = None if isinstance(value, (dict, list)) else value

    for key, value in data.items():
        _walk(str(key), value)

    # Offer a nested key's leaf (``firstName``) only when it is unambiguous and
    # does not shadow a real top-level key.
    leaf_paths: dict[str, list[str]] = {}
    for path in values:
        if "." in path:
            leaf = path.rsplit(".", 1)[1]
            if not leaf.isdigit():
                leaf_paths.setdefault(leaf, []).append(path)
    leaf_aliases = {
        leaf: paths[0] for leaf, paths in leaf_paths.items() if len(paths) == 1 and leaf not in values
    }
    return FlatUserData(values=values, leaf_aliases=leaf_aliases)
