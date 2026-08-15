"""
Persistent templates and profiles.

Daily work is the same form with different data, or the same data across
different forms. Without somewhere to put either, every run re-uploads the PDF,
re-infers semantics, and re-derives a mapping that was already correct
yesterday — and any manual correction is lost the moment the request ends.

* A **template** is keyed by the form's fingerprint and remembers the field
  overrides and options that made a form come out right.
* A **profile** is a named bag of user data, so recurring values are referenced
  rather than repasted.

Storage is JSON files under the configured state directory. That is deliberate:
it needs no service to run, it is inspectable and diffable, and a user can check
their templates into version control. Names are sanitized because they become
filenames.
"""

from __future__ import annotations

import json
import logging
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from .errors import ProfileNotFoundError, TemplateNotFoundError
from .settings import get_settings

logger = logging.getLogger(__name__)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def sanitize_name(name: str) -> str:
    """Reduce a caller-supplied name to something safe to use as a filename.

    Names arrive over HTTP and become paths, so anything that could climb out of
    the store directory has to go before it touches the filesystem.
    """
    cleaned = _SAFE_NAME.sub("-", name.strip()).strip(".-")
    if not cleaned:
        raise ValueError(f"Name {name!r} contains no usable characters")
    return cleaned[:100]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Template(BaseModel):
    """A remembered mapping for one form."""

    name: str
    fingerprint: str = Field(description="Form fingerprint this template applies to")
    description: str = ""
    overrides: dict[str, Any] = Field(
        default_factory=dict,
        description="Explicit field_name -> value assignments applied on every fill",
    )
    key_aliases: dict[str, str] = Field(
        default_factory=dict,
        description="Remembered corrections: field_name -> user_data key to read from",
    )
    flatten: bool = False
    strict: bool = True
    allow_fallback_mapping: bool = False
    use_semantic_inference: bool = False
    created_at: str = Field(default_factory=_utcnow)
    updated_at: str = Field(default_factory=_utcnow)


class Profile(BaseModel):
    """A named, reusable set of user data."""

    name: str
    description: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_utcnow)
    updated_at: str = Field(default_factory=_utcnow)


class JsonStore:
    """A small directory-backed store for one pydantic model type."""

    def __init__(self, directory: Path, model: type[BaseModel], missing_error: type[Exception]):
        self.directory = directory
        self.model = model
        self.missing_error = missing_error

    def _path(self, name: str) -> Path:
        return self.directory / f"{sanitize_name(name)}.json"

    def save(self, item: Any) -> Any:
        """Write an item, replacing any existing one with the same name."""
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self._path(item.name)
        if path.exists():
            item.created_at = self.get(item.name).created_at
        item.updated_at = _utcnow()
        # Write via a temp file in the same directory then rename, so a crash
        # mid-write cannot leave a half-written template behind.
        with tempfile.NamedTemporaryFile(
            "w", dir=self.directory, delete=False, encoding="utf-8", suffix=".tmp"
        ) as handle:
            json.dump(item.model_dump(), handle, indent=2, sort_keys=True)
            temp_path = Path(handle.name)
        temp_path.replace(path)
        return item

    def get(self, name: str) -> Any:
        """Load an item by name, raising the store's typed missing error."""
        path = self._path(name)
        if not path.exists():
            raise self.missing_error(name)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise self.missing_error(name) from exc
        return self.model(**payload)

    def list(self) -> list[Any]:
        """Return every stored item, skipping any that no longer parse."""
        if not self.directory.is_dir():
            return []
        items = []
        for path in sorted(self.directory.glob("*.json")):
            try:
                items.append(self.model(**json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                logger.warning("Skipping unreadable entry %s: %s", path.name, exc)
        return items

    def delete(self, name: str) -> None:
        """Remove an item, raising the typed missing error if it is not there."""
        path = self._path(name)
        if not path.exists():
            raise self.missing_error(name)
        path.unlink()


def template_store() -> JsonStore:
    """Store for form templates."""
    return JsonStore(get_settings().templates_dir, Template, TemplateNotFoundError)


def profile_store() -> JsonStore:
    """Store for named user-data profiles."""
    return JsonStore(get_settings().profiles_dir, Profile, ProfileNotFoundError)


def resolve_fill_inputs(
    *,
    template_name: Optional[str] = None,
    profile_name: Optional[str] = None,
    user_data: Optional[dict[str, Any]] = None,
    overrides: Optional[dict[str, Any]] = None,
) -> tuple[dict[str, Any], dict[str, Any], Optional[Template]]:
    """
    Combine stored template/profile with request-supplied data.

    Precedence is least-to-most specific: profile data is the base, request
    ``user_data`` layers over it, and overrides (template first, then request)
    win outright. That ordering means a stored profile is a default a caller can
    always correct in the moment, never a value they have to go and edit first.
    """
    template: Optional[Template] = None
    resolved_data: dict[str, Any] = {}
    resolved_overrides: dict[str, Any] = {}

    if profile_name:
        resolved_data.update(profile_store().get(profile_name).data)
    if user_data:
        resolved_data.update(user_data)

    if template_name:
        template = template_store().get(template_name)
        resolved_overrides.update(template.overrides)
        # key_aliases remember "this field should read that key", which only
        # resolves once the actual data is in hand.
        for field_name, source_key in template.key_aliases.items():
            if source_key in resolved_data:
                resolved_overrides[field_name] = resolved_data[source_key]
    if overrides:
        resolved_overrides.update(overrides)

    return resolved_data, resolved_overrides, template
