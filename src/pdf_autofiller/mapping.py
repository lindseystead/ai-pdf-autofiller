"""
Data mapping engine for PDF form filling.

Mapping is deterministic-first (normalized keys, aliases, coercion).
Provider-backed fallback is optional and only used for unresolved high-value fields.

Assignment is global rather than greedy: every (field, key) pair is scored, then
the highest-scoring pairs are taken in order. Greedy first-match made results
depend on ``user_data`` insertion order, so the same inputs in a different order
could produce a different document.

Privacy: the optional provider fallback shares user-data *key names* and value
*types* only — never the raw user values — so PII does not leave the service
through this path.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional

from .field_semantics import SemanticClient, strip_json_code_fence
from .models import (
    EnrichedFormField,
    FieldMappingDecision,
    MappingResult,
)

logger = logging.getLogger(__name__)


# Semantic aliases used by deterministic matching.
# Keys are canonical semantic meanings; values are common user-data key variants.
BUILTIN_FIELD_ALIASES: dict[str, list[str]] = {
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
    "job_title": ["title", "position", "occupation"],
    "signature_date": ["date_signed", "signed_date", "sign_date"],
}


def _resolve_aliases_dir() -> Path:
    """Resolve the alias pack directory, falling back when misconfigured."""
    default = Path(__file__).parent / "form_aliases"
    custom_env = os.getenv("FORM_ALIASES_DIR")
    if not custom_env:
        return default

    candidate = Path(custom_env).expanduser()
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


def _load_community_aliases() -> dict[str, list[str]]:
    """Merge optional community alias packs shipped with the package."""
    aliases_dir = _resolve_aliases_dir()
    if not aliases_dir.is_dir():
        return {}

    merged: dict[str, list[str]] = {}
    for path in sorted(aliases_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Skipping invalid alias pack %s: %s", path.name, exc)
            continue
        if not isinstance(payload, dict):
            logger.warning("Skipping alias pack %s: expected JSON object", path.name)
            continue
        for semantic, variants in payload.items():
            if not isinstance(semantic, str) or not isinstance(variants, list):
                continue
            cleaned = [variant for variant in variants if isinstance(variant, str)]
            if cleaned:
                merged.setdefault(semantic, []).extend(cleaned)
    return merged


def _merge_alias_maps(*sources: dict[str, list[str]]) -> dict[str, list[str]]:
    """Union alias lists per semantic, preserving order and dropping duplicates.

    ``dict.update`` would *replace* a semantic's alias list rather than extend
    it, so a community pack that mentions ``first_name`` would delete the
    built-in ``firstname``/``fname``/``given_name`` variants it meant to add to.
    """
    merged: dict[str, list[str]] = {}
    for source in sources:
        for semantic, variants in source.items():
            bucket = merged.setdefault(semantic, [])
            seen = set(bucket)
            for variant in variants:
                if variant not in seen:
                    bucket.append(variant)
                    seen.add(variant)
    return merged


def build_field_aliases() -> dict[str, list[str]]:
    """Build the effective alias table from built-ins plus community packs."""
    return _merge_alias_maps(BUILTIN_FIELD_ALIASES, _load_community_aliases())


FIELD_ALIASES: dict[str, list[str]] = build_field_aliases()


def reload_field_aliases() -> dict[str, list[str]]:
    """Rebuild the alias table in place (picks up FORM_ALIASES_DIR changes)."""
    FIELD_ALIASES.clear()
    FIELD_ALIASES.update(build_field_aliases())
    return FIELD_ALIASES


def alias_pack_status() -> dict[str, str]:
    """Return alias-pack metadata for health checks."""
    aliases_dir = _resolve_aliases_dir()
    pack_count = len(list(aliases_dir.glob("*.json"))) if aliases_dir.is_dir() else 0
    return {
        "alias_directory": str(aliases_dir),
        "alias_pack_count": str(pack_count),
    }


def normalize_key(key: str) -> str:
    """
    Normalize a key string for matching.

    Converts to lowercase, standardizes separators to underscores, and
    removes punctuation. This allows matching "First-Name" to "first_name".

    Args:
        key: Original key string

    Returns:
        Normalized key in snake_case format
    """
    key = key.lower()
    key = re.sub(r"[\s\-_\.]+", "_", key)
    key = re.sub(r"[^\w_]", "", key)
    key = re.sub(r"_+", "_", key)
    key = key.strip("_")

    return key


def flatten_user_data(
    data: Any,
    *,
    prefix: str = "",
    separator: str = ".",
    max_depth: int = 8,
    _depth: int = 0,
) -> dict[str, Any]:
    """
    Flatten nested user data into dotted paths.

    Real profile data arrives nested — from a CRM, an HRIS, an automation node —
    and matching only ever inspected top-level keys, so a nested payload mapped
    nothing and reported the *container* key as unmapped. Both the full path and
    the leaf are made available to the matcher by :func:`candidate_keys`.

    Lists are indexed (``phones.0``) so repeated groups stay addressable.

    Top-level keys beginning with an underscore are dropped. ``init --annotate``
    emits a ``_fields`` block describing each key, because JSON has no comments;
    without this the annotations would come back as dozens of unmapped keys and
    bury the ones that actually matter.
    """
    flat: dict[str, Any] = {}
    if _depth >= max_depth:
        if prefix:
            flat[prefix] = data
        return flat

    if isinstance(data, dict):
        for key, value in data.items():
            if _depth == 0 and isinstance(key, str) and key.startswith("_"):
                continue
            path = f"{prefix}{separator}{key}" if prefix else str(key)
            if isinstance(value, (dict, list)):
                flat.update(
                    flatten_user_data(
                        value,
                        prefix=path,
                        separator=separator,
                        max_depth=max_depth,
                        _depth=_depth + 1,
                    )
                )
            else:
                flat[path] = value
    elif isinstance(data, list):
        for index, value in enumerate(data):
            path = f"{prefix}{separator}{index}" if prefix else str(index)
            if isinstance(value, (dict, list)):
                flat.update(
                    flatten_user_data(
                        value,
                        prefix=path,
                        separator=separator,
                        max_depth=max_depth,
                        _depth=_depth + 1,
                    )
                )
            else:
                flat[path] = value
    elif prefix:
        flat[prefix] = data

    return flat


def candidate_keys(path: str) -> list[str]:
    """Return the normalized forms a dotted path may match against.

    ``address.city`` should match a field meaning ``city`` (leaf) as well as one
    meaning ``address_city`` (full path), so both are offered to the matcher.
    """
    normalized_full = normalize_key(path.replace(".", "_"))
    leaf = normalize_key(path.rsplit(".", 1)[-1])
    return [normalized_full] if normalized_full == leaf else [normalized_full, leaf]


def coerce_value(value: Any, expected_type: str) -> tuple[Optional[str], bool]:
    """
    Coerce a value to match the expected data type.

    Performs type conversion and validation. Returns a flag indicating whether
    the coercion was ambiguous and requires human review.

    Args:
        value: Value to coerce
        expected_type: One of "string", "date", "number", "boolean"

    Returns:
        Tuple of (coerced_value, requires_review)
        - coerced_value: String representation, or None if value is None
        - requires_review: True if coercion was ambiguous or failed
    """
    if value is None:
        return None, False

    str_value = str(value).strip()

    if expected_type == "string":
        return str_value, False

    elif expected_type == "date":
        # Only accept ISO format YYYY-MM-DD
        date_pattern = r"^\d{4}-\d{2}-\d{2}$"
        if re.match(date_pattern, str_value):
            try:
                datetime.strptime(str_value, "%Y-%m-%d")
                return str_value, False
            except ValueError:
                # Invalid date (e.g., 2024-13-45)
                return str_value, True
        else:
            # Wrong format entirely
            return str_value, True

    elif expected_type == "number":
        try:
            float_val = float(str_value)
            # Prefer integer representation when possible
            if float_val.is_integer():
                return str(int(float_val)), False
            return str(float_val), False
        except (ValueError, OverflowError):
            return str_value, True

    elif expected_type == "boolean":
        str_lower = str_value.lower()
        if str_lower in ("true", "yes", "1", "on"):
            return "true", False
        elif str_lower in ("false", "no", "0", "off"):
            return "false", False
        else:
            # Ambiguous boolean value
            return str_value, True

    return str_value, False


def find_deterministic_match(
    semantic_meaning: str,
    user_data: dict[str, Any],
    expected_type: str,
) -> tuple[Optional[str], Optional[str], float, str, bool]:
    """
    Find a deterministic match for a semantic meaning.

    Tries direct normalized matching first, then falls back to alias matching.
    Returns None if no match found. All matching is case-insensitive, handles
    key normalization, and understands nested (dotted) paths.

    Args:
        semantic_meaning: Semantic meaning to match (e.g., "first_name")
        user_data: User-provided data dictionary
        expected_type: Expected data type for type coercion

    Returns:
        Tuple of (matched_key, matched_value, confidence, reason, requires_review)
    """
    scored = _score_candidates(semantic_meaning, user_data, expected_type)
    if not scored:
        return None, None, 0.0, "No deterministic match found", False

    best = scored[0]
    return best.key, best.value, best.confidence, best.reason, best.requires_review


class _Candidate:
    """A scored (semantic, user-key) pairing considered during assignment."""

    __slots__ = ("key", "value", "confidence", "reason", "requires_review", "rank")

    def __init__(
        self,
        key: str,
        value: Optional[str],
        confidence: float,
        reason: str,
        requires_review: bool,
        rank: int,
    ) -> None:
        self.key = key
        self.value = value
        self.confidence = confidence
        self.reason = reason
        self.requires_review = requires_review
        self.rank = rank


def _score_candidates(
    semantic_meaning: str,
    user_data: dict[str, Any],
    expected_type: str,
) -> list[_Candidate]:
    """Score every user key against one semantic meaning, best first."""
    normalized_semantic = normalize_key(semantic_meaning)
    aliases = {normalize_key(alias) for alias in FIELD_ALIASES.get(semantic_meaning, [])}

    candidates: list[_Candidate] = []
    for user_key, user_value in user_data.items():
        forms = candidate_keys(user_key)

        matched_rank: Optional[int] = None
        reason = ""
        if normalized_semantic in forms:
            # Exact path beats leaf-only so address.city loses to a literal city.
            matched_rank = 0 if forms[0] == normalized_semantic else 1
            reason = f"Direct match: '{user_key}' matches semantic '{semantic_meaning}'"
        elif aliases.intersection(forms):
            matched_rank = 2 if forms[0] in aliases else 3
            reason = (
                f"Alias match: '{user_key}' matches semantic '{semantic_meaning}' via alias"
            )

        if matched_rank is None:
            continue

        coerced_value, requires_review = coerce_value(user_value, expected_type)
        base = 0.95 if matched_rank <= 1 else 0.90
        confidence = base if not requires_review else base - 0.25
        candidates.append(
            _Candidate(user_key, coerced_value, confidence, reason, requires_review, matched_rank)
        )

    candidates.sort(key=lambda c: (c.rank, -c.confidence, c.key))
    return candidates


def semantic_fallback_mapping(
    unmapped_fields: list[EnrichedFormField],
    user_data: dict[str, Any],
    api_key: Optional[str] = None,
) -> dict[str, tuple[str, Optional[str], float, str]]:
    """
    Use provider-backed fallback to map unmapped fields when deterministic matching fails.

    Only called for fields that couldn't be matched deterministically.
    Returns empty dict if the semantic client is unavailable or if no fields provided.

    Args:
        unmapped_fields: Fields that failed deterministic matching
        user_data: User-provided data dictionary
        api_key: Optional provider API key

    Returns:
        Dictionary mapping field_name -> (matched_key, matched_value, confidence, reason)
    """
    if not unmapped_fields:
        return {}

    client = SemanticClient(api_key=api_key)
    if not client.is_available():
        return {}

    # Prepare field metadata for provider-backed fallback.
    fields_info = []
    for field in unmapped_fields:
        fields_info.append(
            {
                "field_name": field.field.name,
                "semantic_meaning": field.semantics.semantic_meaning,
                "expected_type": field.semantics.expected_data_type,
                "required": field.field.required,
            }
        )

    user_data_keys = list(user_data.keys())
    # Privacy: send only key names and value *types* to the provider. Raw user
    # values (which are typically PII) are withheld so they never leave the
    # service via the fallback path.
    user_data_types = {key: type(value).__name__ for key, value in user_data.items()}

    prompt = f"""Map the following PDF form fields to user data keys.

Form Fields:
{json.dumps(fields_info, indent=2)}

Available User Data Keys:
{json.dumps(user_data_keys, indent=2)}

User Data Value Types (type names only; raw values withheld for privacy):
{json.dumps(user_data_types, indent=2)}

For each field, determine which user data key best matches the semantic meaning.
Only choose matched_key values from the Available User Data Keys list.
Return a JSON object mapping field_name to:
- matched_key: The user data key that matches (or null if no match)
- confidence: Float between 0.0 and 1.0
- reason: Brief explanation

Example response:
{{
  "txtFirstName": {{
    "matched_key": "firstname",
    "confidence": 0.85,
    "reason": "User key 'firstname' matches semantic 'first_name'"
  }}
}}"""

    try:
        content = client.create_json_completion(
            system_prompt=(
                "You are a data mapping assistant. "
                "Map form fields to user data keys. Return ONLY valid JSON."
            ),
            user_prompt=prompt,
            temperature=0.2,
        )

        fallback_result = json.loads(strip_json_code_fence(content))

        # Convert to our format
        result = {}
        for field in unmapped_fields:
            field_name = field.field.name
            if field_name in fallback_result:
                match_info = fallback_result[field_name]
                matched_key = match_info.get("matched_key")
                confidence = float(match_info.get("confidence", 0.0))
                reason = match_info.get("reason", "Fallback mapping")

                if matched_key and matched_key in user_data:
                    # Coerce the value
                    coerced_value, _ = coerce_value(
                        user_data[matched_key], field.semantics.expected_data_type
                    )
                    result[field_name] = (matched_key, coerced_value, confidence, reason)

        return result

    except (RuntimeError, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        logger.warning("Provider fallback mapping failed: %s", exc)
        return {}


def _apply_overrides(
    enriched_fields: Iterable[EnrichedFormField],
    overrides: dict[str, Any],
) -> tuple[list[FieldMappingDecision], set[str]]:
    """Turn an explicit ``{field_name: value}`` map into decisions.

    Overrides exist because no matcher will ever be right about every field, and
    the alternative — editing the PDF by hand — throws away the rest of the run.
    An override is authoritative: full confidence, never flagged for review.
    """
    by_name = {field.field.name: field for field in enriched_fields}
    decisions: list[FieldMappingDecision] = []
    consumed: set[str] = set()

    for field_name, raw_value in overrides.items():
        enriched = by_name.get(field_name)
        if enriched is None:
            logger.warning("Override targets unknown field %r; ignoring", field_name)
            continue
        coerced, _ = coerce_value(raw_value, enriched.semantics.expected_data_type)
        decisions.append(
            FieldMappingDecision(
                field_name=field_name,
                semantic_meaning=enriched.semantics.semantic_meaning,
                selected_value=coerced,
                confidence=1.0,
                reason="Explicit override supplied by caller",
                requires_review=False,
            )
        )
        consumed.add(field_name)

    return decisions, consumed


def _assign_best_first(
    fields: list[EnrichedFormField],
    flat_data: dict[str, Any],
    allow_key_reuse: bool,
) -> tuple[dict[str, FieldMappingDecision], set[str]]:
    """Score every (field, key) pair, then take the best pairings in order.

    Greedy first-match made the outcome depend on ``user_data`` insertion order,
    so the same data submitted twice could fill a form differently. Scoring
    everything up front and assigning best-first removes that.
    """
    scored: list[tuple[float, int, str, EnrichedFormField, _Candidate]] = []
    for enriched_field in fields:
        for candidate in _score_candidates(
            enriched_field.semantics.semantic_meaning,
            flat_data,
            enriched_field.semantics.expected_data_type,
        ):
            scored.append(
                (
                    -candidate.confidence,
                    candidate.rank,
                    enriched_field.field.name,
                    enriched_field,
                    candidate,
                )
            )
    scored.sort(key=lambda item: (item[0], item[1], item[2]))

    assigned: dict[str, FieldMappingDecision] = {}
    used_user_keys: set[str] = set()
    for _, _, field_name, enriched_field, candidate in scored:
        if field_name in assigned:
            continue
        if not allow_key_reuse and candidate.key in used_user_keys:
            continue

        used_user_keys.add(candidate.key)
        assigned[field_name] = FieldMappingDecision(
            field_name=field_name,
            semantic_meaning=enriched_field.semantics.semantic_meaning,
            selected_value=candidate.value,
            confidence=candidate.confidence,
            reason=candidate.reason,
            requires_review=candidate.requires_review or candidate.confidence < 0.80,
        )

    return assigned, used_user_keys


def _apply_provider_fallback(
    unmapped_fields: list[EnrichedFormField],
    flat_data: dict[str, Any],
    used_user_keys: set[str],
    decisions: list[FieldMappingDecision],
    api_key: Optional[str],
) -> list[EnrichedFormField]:
    """Ask the provider about fields deterministic matching could not resolve.

    Restricted to high-value fields — required, or confidently understood —
    because the provider costs money and latency, and a field nobody needs is
    not worth either. Appends to ``decisions`` and returns what remains unmapped.
    """
    high_value = [
        f for f in unmapped_fields if f.field.required or f.semantics.confidence_score > 0.8
    ]
    if not high_value:
        return unmapped_fields

    fallback_mappings = semantic_fallback_mapping(high_value, flat_data, api_key)
    still_unmapped = list(unmapped_fields)

    for enriched_field in high_value:
        field_name = enriched_field.field.name
        if field_name not in fallback_mappings:
            continue

        matched_key, matched_value, confidence, reason = fallback_mappings[field_name]
        if not matched_key or matched_key in used_user_keys:
            continue

        used_user_keys.add(matched_key)
        coerced_value, requires_review = coerce_value(
            matched_value, enriched_field.semantics.expected_data_type
        )
        decisions.append(
            FieldMappingDecision(
                field_name=field_name,
                semantic_meaning=enriched_field.semantics.semantic_meaning,
                selected_value=coerced_value,
                confidence=confidence,
                reason=reason,
                requires_review=requires_review or confidence < 0.80,
            )
        )
        still_unmapped.remove(enriched_field)

    return still_unmapped


def map_user_data_to_fields(
    enriched_fields: list[EnrichedFormField],
    user_data: dict[str, Any],
    *,
    strict: bool = False,
    allow_fallback_mapping: bool = True,
    api_key: Optional[str] = None,
    overrides: Optional[dict[str, Any]] = None,
    allow_key_reuse: bool = True,
    max_depth: int = 8,
) -> MappingResult:
    """
    Map user-provided structured data to PDF form fields.

    Uses deterministic matching first (exact/normalized/aliases), then optional
    fallback mapping for ambiguous cases.

    Args:
        enriched_fields: List of form fields with inferred semantics
        user_data: User-provided data dictionary (may be nested)
        strict: If True, only use deterministic matching (no fallback mapping)
        allow_fallback_mapping: If True, use fallback mapping for unmapped required/high-value fields
        api_key: Optional provider API key for fallback mapping
        overrides: Explicit ``{field_name: value}`` assignments that win outright
        allow_key_reuse: If True, one user key may fill several fields (a name
            repeated across pages). If False, each key is consumed once.
        max_depth: Maximum nesting depth to flatten in ``user_data``

    Returns:
        MappingResult with decisions, missing required fields, and unmapped keys

    Example:
        >>> fields = [
        ...     EnrichedFormField(
        ...         field=FormField(name="txtFirstName", field_type="text", required=True, page_number=1),
        ...         semantics=FieldSemantics(semantic_meaning="first_name", expected_data_type="string", confidence_score=0.95)
        ...     )
        ... ]
        >>> user_data = {"firstname": "John", "lastname": "Doe"}
        >>> result = map_user_data_to_fields(fields, user_data)
        >>> result.decisions[0].selected_value
        'John'
    """
    flat_data = flatten_user_data(user_data, max_depth=max_depth)

    decisions, overridden = _apply_overrides(enriched_fields, overrides or {})
    pending = [f for f in enriched_fields if f.field.name not in overridden]

    assigned, used_user_keys = _assign_best_first(pending, flat_data, allow_key_reuse)
    decisions.extend(assigned.values())

    unmapped_fields = [f for f in pending if f.field.name not in assigned]
    if not strict and allow_fallback_mapping and unmapped_fields:
        unmapped_fields = _apply_provider_fallback(
            unmapped_fields, flat_data, used_user_keys, decisions, api_key
        )

    missing_required = [f.field.name for f in unmapped_fields if f.field.required]
    unmapped_user_keys = [key for key in flat_data if key not in used_user_keys]

    return MappingResult(
        decisions=decisions,
        missing_required=missing_required,
        unmapped_user_keys=unmapped_user_keys,
    )
