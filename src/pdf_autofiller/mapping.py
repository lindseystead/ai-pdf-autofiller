"""
Data mapping engine for PDF form filling.

Mapping is deterministic-first (normalized keys, aliases, coercion).
Provider-backed fallback is optional and only used for unresolved high-value fields.

Privacy: the optional provider fallback shares user-data *key names* and value
*types* only — never the raw user values — so PII does not leave the service
through this path.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from .aliases import (
    AliasRegistry,
    get_default_registry,
    normalize_key,
)
from .field_semantics import SemanticClient, strip_json_code_fence
from .models import (
    EnrichedFormField,
    FieldMappingDecision,
    MappingResult,
)

logger = logging.getLogger(__name__)

# Backward-compatible module alias: live view of the default registry.
# Prefer AliasRegistry / get_default_registry() in new code.
FIELD_ALIASES: dict[str, list[str]] = get_default_registry().aliases


def alias_pack_status() -> dict[str, str]:
    """Return alias-pack metadata for health checks."""
    return get_default_registry().status()


def alias_equivalence_set(key: str, registry: AliasRegistry | None = None) -> set[str]:
    """
    Return every normalized key that shares an alias pack with ``key``.

    Alias packs are keyed by canonical semantics (``first_name``), but
    field-name fallback often produces a synonym (``firstname`` after
    stripping ``txt``). Matching must treat the whole cluster as equivalent
    so ``given_name`` still maps when the derived semantic is ``firstname``.
    """
    return (registry or get_default_registry()).equivalence_set(key)


def canonicalize_semantic(key: str, registry: AliasRegistry | None = None) -> str:
    """Map a synonym onto its canonical alias-pack key when one exists."""
    return (registry or get_default_registry()).canonicalize(key)


def coerce_value(value: Any, expected_type: str) -> tuple[str | None, bool]:
    """
    Coerce a value to match the expected data type.

    Returns ``(coerced_value, requires_review)``.
    """
    if value is None:
        return None, False

    str_value = str(value).strip()

    if expected_type == "string":
        return str_value, False

    if expected_type == "date":
        if re.match(r"^\d{4}-\d{2}-\d{2}$", str_value):
            try:
                datetime.strptime(str_value, "%Y-%m-%d")
                return str_value, False
            except ValueError:
                return str_value, True
        return str_value, True

    if expected_type == "number":
        try:
            float_val = float(str_value)
            if float_val.is_integer():
                return str(int(float_val)), False
            return str(float_val), False
        except (ValueError, OverflowError):
            return str_value, True

    if expected_type == "boolean":
        str_lower = str_value.lower()
        if str_lower in ("true", "yes", "1", "on"):
            return "true", False
        if str_lower in ("false", "no", "0", "off"):
            return "false", False
        return str_value, True

    return str_value, False


def find_deterministic_match(
    semantic_meaning: str,
    user_data: dict[str, Any],
    expected_type: str,
    registry: AliasRegistry | None = None,
) -> tuple[str | None, str | None, float, str, bool]:
    """
    Find a deterministic match for a semantic meaning.

    Tries direct normalized matching first, then alias-cluster matching.
    """
    active = registry or get_default_registry()
    normalized_semantic = normalize_key(semantic_meaning)
    equivalence = active.equivalence_set(semantic_meaning)

    for user_key, user_value in user_data.items():
        normalized_key = normalize_key(user_key)
        if normalized_key == normalized_semantic:
            coerced_value, requires_review = coerce_value(user_value, expected_type)
            confidence = 0.95 if not requires_review else 0.70
            reason = f"Direct match: '{user_key}' matches semantic '{semantic_meaning}'"
            return user_key, coerced_value, confidence, reason, requires_review

    for user_key, user_value in user_data.items():
        normalized_key = normalize_key(user_key)
        if normalized_key in equivalence:
            coerced_value, requires_review = coerce_value(user_value, expected_type)
            confidence = 0.90 if not requires_review else 0.65
            reason = (
                f"Alias match: '{user_key}' matches semantic "
                f"'{semantic_meaning}' via alias cluster"
            )
            return user_key, coerced_value, confidence, reason, requires_review

    return None, None, 0.0, "No deterministic match found", False


def semantic_fallback_mapping(
    unmapped_fields: list[EnrichedFormField],
    user_data: dict[str, Any],
    api_key: str | None = None,
) -> dict[str, tuple[str, str | None, float, str]]:
    """
    Use provider-backed fallback to map unmapped fields when deterministic matching fails.

    Only key names and value *types* are sent to the provider — never raw values.
    """
    if not unmapped_fields:
        return {}

    client = SemanticClient(api_key=api_key)
    if not client.is_available():
        logger.info("Provider fallback skipped: semantic client unavailable")
        return {}

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
            model="gpt-4o-mini",
            temperature=0.2,
        )
        fallback_result = json.loads(strip_json_code_fence(content))

        result: dict[str, tuple[str, str | None, float, str]] = {}
        for field in unmapped_fields:
            field_name = field.field.name
            if field_name not in fallback_result:
                continue
            match_info = fallback_result[field_name]
            matched_key = match_info.get("matched_key")
            confidence = float(match_info.get("confidence", 0.0))
            reason = match_info.get("reason", "Fallback mapping")

            if matched_key and matched_key in user_data:
                coerced_value, _ = coerce_value(
                    user_data[matched_key],
                    field.semantics.expected_data_type,
                )
                result[field_name] = (matched_key, coerced_value, confidence, reason)
        return result
    except (RuntimeError, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        logger.warning("Provider fallback mapping failed: %s", exc)
        return {}


def map_user_data_to_fields(
    enriched_fields: list[EnrichedFormField],
    user_data: dict[str, Any],
    *,
    strict: bool = False,
    allow_fallback_mapping: bool = False,
    api_key: str | None = None,
    registry: AliasRegistry | None = None,
) -> MappingResult:
    """
    Map user-provided structured data to PDF form fields.

    Uses deterministic matching first, then optional provider fallback for
    unresolved required/high-value fields.
    """
    decisions: list[FieldMappingDecision] = []
    unmapped_fields: list[EnrichedFormField] = []
    used_user_keys: set[str] = set()
    active = registry or get_default_registry()

    for enriched_field in enriched_fields:
        semantic = enriched_field.semantics.semantic_meaning
        expected_type = enriched_field.semantics.expected_data_type

        matched_key, matched_value, confidence, reason, requires_review = (
            find_deterministic_match(
                semantic,
                user_data,
                expected_type,
                registry=active,
            )
        )

        if matched_key:
            used_user_keys.add(matched_key)
            decisions.append(
                FieldMappingDecision(
                    field_name=enriched_field.field.name,
                    semantic_meaning=semantic,
                    selected_value=matched_value,
                    confidence=confidence,
                    reason=reason,
                    requires_review=requires_review or confidence < 0.80,
                )
            )
        else:
            unmapped_fields.append(enriched_field)

    if not strict and allow_fallback_mapping and unmapped_fields:
        high_value_fields = [
            f
            for f in unmapped_fields
            if f.field.required or f.semantics.confidence_score > 0.8
        ]

        if high_value_fields:
            fallback_mappings = semantic_fallback_mapping(
                high_value_fields, user_data, api_key
            )

            for enriched_field in high_value_fields[:]:
                field_name = enriched_field.field.name
                if field_name not in fallback_mappings:
                    continue
                matched_key, matched_value, confidence, reason = fallback_mappings[
                    field_name
                ]
                if matched_key and matched_key not in used_user_keys:
                    used_user_keys.add(matched_key)
                    coerced_value, requires_review = coerce_value(
                        matched_value,
                        enriched_field.semantics.expected_data_type,
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
                    unmapped_fields.remove(enriched_field)

    missing_required = [f.field.name for f in unmapped_fields if f.field.required]
    unmapped_user_keys = [key for key in user_data if key not in used_user_keys]

    return MappingResult(
        decisions=decisions,
        missing_required=missing_required,
        unmapped_user_keys=unmapped_user_keys,
    )
