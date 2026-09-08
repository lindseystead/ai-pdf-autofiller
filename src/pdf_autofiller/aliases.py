"""
Alias registry for deterministic field matching.

Alias packs map canonical semantic meanings (``first_name``) to common
user-data key variants (``firstname``, ``given_name``). Packs are loaded
explicitly via ``AliasRegistry.load`` — not by mutating a module global at
import time — so tests and operators can control which packs are active.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Built-in synonym clusters. Keys are canonical semantics; values are variants
# callers commonly send. Community JSON packs extend this set.
BUILTIN_ALIASES: dict[str, list[str]] = {
    "first_name": ["firstname", "given_name", "forename", "fname"],
    "last_name": ["lastname", "surname", "family_name", "lname"],
    "middle_name": ["middlename", "middle_initial", "mi"],
    "full_name": ["fullname", "name", "legal_name"],
    "date_of_birth": ["dob", "birth_date", "birthdate", "birthday"],
    "email_address": ["email", "emailaddress", "e_mail"],
    "phone_number": ["phone", "mobile", "cell", "telephone", "tel"],
    "street_address": ["address", "street", "addr1", "address_line_1", "address1"],
    "address_line_2": ["addr2", "address2", "apt", "suite", "unit"],
    "city": ["town", "municipality"],
    "state": ["province", "region", "state_province"],
    "postal_code": ["zip", "zipcode", "zip_code", "postcode"],
    "country": ["nation"],
    "social_security_number": ["ssn", "social_security", "tax_id", "national_id"],
    "employer": ["company", "employer_name", "organization"],
    "job_title": ["title", "position", "occupation", "jobtitle"],
    "employee_name": ["employeename", "worker_name", "staff_name"],
    "signature_date": ["date_signed", "signed_date", "sign_date"],
}


def normalize_key(key: str) -> str:
    """Normalize a key for matching: camelCase split, lowercase, underscores.

    AcroForm fields are often ``txtFirstName`` / ``NameLine1``. Splitting
    camelCase and letter/digit boundaries before lowercasing lets those map
    onto snake_case alias packs (``first_name``, ``name_line_1``).
    """
    key = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    key = re.sub(r"([A-Za-z])([0-9])", r"\1_\2", key)
    key = key.lower()
    key = re.sub(r"[\s\-_\.]+", "_", key)
    key = re.sub(r"[^\w_]", "", key)
    key = re.sub(r"_+", "_", key)
    return key.strip("_")


def packaged_aliases_dir() -> Path:
    """Directory of JSON alias packs shipped with the package."""
    return Path(__file__).parent / "form_aliases"


def resolve_aliases_dir(custom: str | Path | None = None) -> Path:
    """
    Resolve the alias-pack directory.

    ``FORM_ALIASES_DIR`` (or ``custom``) **replaces** the packaged directory; it
    does not merge with it. Built-in ``BUILTIN_ALIASES`` still apply.
    """
    default = packaged_aliases_dir()
    raw = custom if custom is not None else os.getenv("FORM_ALIASES_DIR")
    if not raw:
        return default

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    else:
        candidate = candidate.resolve()

    if not candidate.is_dir():
        logger.warning(
            "FORM_ALIASES_DIR is not a directory (%s); using package defaults",
            candidate,
        )
        return default
    return candidate


def load_pack_file(path: Path) -> dict[str, list[str]]:
    """Load one JSON alias pack; return {} and log on invalid content."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Skipping invalid alias pack %s: %s", path.name, exc)
        return {}
    if not isinstance(payload, dict):
        logger.warning("Skipping alias pack %s: expected JSON object", path.name)
        return {}

    merged: dict[str, list[str]] = {}
    for semantic, variants in payload.items():
        if not isinstance(semantic, str) or not isinstance(variants, list):
            continue
        cleaned = [variant for variant in variants if isinstance(variant, str)]
        if cleaned:
            merged[semantic] = cleaned
    return merged


def load_packs_from_dir(aliases_dir: Path) -> dict[str, list[str]]:
    """Merge all ``*.json`` packs in a directory."""
    if not aliases_dir.is_dir():
        return {}
    merged: dict[str, list[str]] = {}
    for path in sorted(aliases_dir.glob("*.json")):
        for semantic, variants in load_pack_file(path).items():
            merged.setdefault(semantic, []).extend(variants)
    return merged


def _merge_alias_maps(*maps: dict[str, list[str]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for mapping in maps:
        for semantic, variants in mapping.items():
            bucket = merged.setdefault(semantic, [])
            for variant in variants:
                if variant not in bucket:
                    bucket.append(variant)
    return merged


@dataclass
class AliasRegistry:
    """Immutable-enough view of alias clusters used by deterministic matching."""

    aliases: dict[str, list[str]] = field(default_factory=dict)
    pack_directory: Path = field(default_factory=packaged_aliases_dir)
    pack_count: int = 0

    @classmethod
    def load(
        cls,
        *,
        pack_dir: str | Path | None = None,
        include_builtin: bool = True,
    ) -> AliasRegistry:
        """
        Build a registry from built-ins plus JSON packs.

        Args:
            pack_dir: Override pack directory (same semantics as FORM_ALIASES_DIR).
            include_builtin: When False, only JSON packs are used (tests).
        """
        directory = resolve_aliases_dir(pack_dir)
        packs = load_packs_from_dir(directory)
        pack_count = len(list(directory.glob("*.json"))) if directory.is_dir() else 0
        base = dict(BUILTIN_ALIASES) if include_builtin else {}
        return cls(
            aliases=_merge_alias_maps(base, packs),
            pack_directory=directory,
            pack_count=pack_count,
        )

    def equivalence_set(self, key: str) -> set[str]:
        """Every normalized key that shares an alias cluster with ``key``."""
        normalized = normalize_key(key)
        cluster: set[str] = {normalized}
        for canon, aliases in self.aliases.items():
            members = {normalize_key(canon)} | {normalize_key(a) for a in aliases}
            if normalized in members:
                cluster |= members
        return cluster

    def canonicalize(self, key: str) -> str:
        """Map a synonym onto its canonical pack key when one exists."""
        normalized = normalize_key(key)
        for canon, aliases in self.aliases.items():
            members = {normalize_key(canon)} | {normalize_key(a) for a in aliases}
            if normalized in members:
                return canon
        return normalized

    def status(self) -> dict[str, str]:
        """Metadata for health checks."""
        return {
            "alias_directory": str(self.pack_directory),
            "alias_pack_count": str(self.pack_count),
        }


_default_registry: AliasRegistry | None = None


def get_default_registry() -> AliasRegistry:
    """Process-wide registry (lazy). Reload requires ``set_default_registry``."""
    global _default_registry
    if _default_registry is None:
        _default_registry = AliasRegistry.load()
    return _default_registry


def set_default_registry(registry: AliasRegistry | None) -> None:
    """Replace or clear the process-wide registry (tests / controlled reload)."""
    global _default_registry
    _default_registry = registry
