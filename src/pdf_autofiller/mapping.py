"""
Data mapping engine for PDF form filling.

Mapping is deterministic-first: normalized names, alias clusters, and dates and
numbers validated without rewriting. The opt-in AI key fallback asks the model to
pick a user key only for unresolved fields that are required or confidently typed.

Privacy: the AI key fallback shares user-data *key names* and value
*types* only — never the raw user values — so PII does not leave the service
through this path.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any, Literal

from .aliases import (
    AliasRegistry,
    get_default_registry,
    normalize_key,
)
from .field_semantics import SemanticClient, strip_json_code_fence
from .field_utils import opaque_mapping_hints
from .models import (
    EnrichedFormField,
    FieldMappingDecision,
    MappingResult,
)
from .user_data import flatten_user_data

logger = logging.getLogger(__name__)

# Deterministic expected-type hints for known semantics (and name patterns).
# Used by fallback enrichment so coerce_value runs on the default (non-AI) path.
_DATE_SEMANTICS = frozenset(
    {
        "date_of_birth",
        "signature_date",
        "start_date",
        "end_date",
        "hire_date",
        "termination_date",
        "effective_date",
        "signed_date",
    }
)
_BOOLEAN_SEMANTICS = frozenset(
    {
        "consent",
        "agree",
        "acknowledgment",
    }
)


def expected_type_for_semantic(
    semantic: str,
    *,
    field_type: str | None = None,
) -> Literal["string", "date", "number", "boolean"]:
    """
    Infer a coerce target for deterministic enrichment.

    Button widgets default to ``boolean``. Known date/boolean semantics (and
    ``*_date`` / ``date_*`` name patterns) get typed so US/common date strings
    normalize on the default path without AI.
    """
    if field_type == "button":
        return "boolean"

    normalized = normalize_key(semantic)
    if normalized in _DATE_SEMANTICS or normalized.endswith("_date") or normalized.startswith("date_"):
        return "date"
    if normalized in _BOOLEAN_SEMANTICS or normalized.startswith(("is_", "has_", "chk_")):
        return "boolean"
    return "string"


def alias_pack_status() -> dict[str, str]:
    """Return alias-pack metadata for health checks."""
    return get_default_registry().status()


def canonicalize_semantic(key: str, registry: AliasRegistry | None = None) -> str:
    """Map a synonym onto its canonical alias-pack key when one exists."""
    return (registry or get_default_registry()).canonicalize(key)


_DECIMAL_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)")


def coerce_value(value: Any, expected_type: str) -> tuple[str | None, bool]:
    """
    Coerce a value to match the expected data type.

    Returns ``(coerced_value, requires_review)``.

    Dates and numbers are validated, never rewritten: the caller's string is written
    verbatim so the form receives the format the user chose (reformatting to
    ISO would silently break forms printed as ``MM/DD/YYYY`` and would have to
    guess between month-first and day-first readings). Unparseable dates and
    two-digit years (ambiguous century) are flagged for review.
    """
    if value is None:
        return None, False

    str_value = str(value).strip()

    if expected_type == "string":
        return str_value, False

    if expected_type == "date":
        date_formats = (
            "%Y-%m-%d",
            "%m/%d/%Y",
            "%m-%d-%Y",
            "%d/%m/%Y",
            "%d-%m-%Y",
            "%Y/%m/%d",
            "%b %d, %Y",
            "%B %d, %Y",
        )
        for fmt in date_formats:
            try:
                datetime.strptime(str_value, fmt)
                return str_value, False
            except ValueError:
                continue
        return str_value, True

    if expected_type == "number":
        # Validated, never rewritten: float() would drop leading zeros (ZIP
        # "02134") and lose precision on long account numbers.
        return str_value, _DECIMAL_RE.fullmatch(str_value) is None

    if expected_type == "boolean":
        str_lower = str_value.lower()
        if str_lower in ("true", "yes", "1", "on"):
            return "true", False
        if str_lower in ("false", "no", "0", "off"):
            return "false", False
        return str_value, True

    return str_value, False


def coerce_for_field(
    value: Any,
    expected_type: str,
    field_type: str | None = None,
) -> tuple[str | None, bool]:
    """Coerce a value for a specific widget type.

    Button widgets accept either a boolean (checkbox) or an export-state name
    (radio option such as ``Female``). Only the writer knows the widget's
    declared states, so non-boolean strings pass through unflagged and the
    writer validates them — reporting ``unresolved_button_state`` when they
    match no state — instead of the mapper discarding every radio option.
    """
    if field_type == "button" and value is not None:
        coerced, requires_review = coerce_value(value, "boolean")
        if requires_review and str(value).strip():
            return str(value).strip(), False
        return coerced, requires_review
    return coerce_value(value, expected_type)


def match_field_name(
    field_name: str,
    user_data: dict[str, Any],
    expected_type: str,
    field_type: str | None = None,
) -> tuple[str | None, str | None, float, str, bool]:
    """Match a user key that addresses the field by its own (normalized) name."""
    normalized_field = normalize_key(field_name)
    for user_key, user_value in user_data.items():
        if user_key == field_name or normalize_key(user_key) == normalized_field:
            coerced_value, requires_review = coerce_for_field(user_value, expected_type, field_type)
            confidence = 0.98 if not requires_review else 0.70
            reason = f"Field-name match: '{user_key}' addresses field '{field_name}'"
            return user_key, coerced_value, confidence, reason, requires_review
    return None, None, 0.0, "No field-name match", False


def find_deterministic_match(
    semantic_meaning: str,
    user_data: dict[str, Any],
    expected_type: str,
    registry: AliasRegistry | None = None,
    *,
    field_name: str | None = None,
    field_type: str | None = None,
) -> tuple[str | None, str | None, float, str, bool]:
    """
    Find a deterministic match for a semantic meaning.

    Tries an exact field-name match first (the caller addressed the widget by
    its own name, e.g. ``applicant.lastName``), then direct normalized
    semantic matching, then alias-cluster matching.
    """
    active = registry or get_default_registry()
    normalized_semantic = normalize_key(semantic_meaning)
    equivalence = active.equivalence_set(semantic_meaning)

    if field_name:
        by_name = match_field_name(field_name, user_data, expected_type, field_type)
        if by_name[0]:
            return by_name

    for user_key, user_value in user_data.items():
        normalized_key = normalize_key(user_key)
        if normalized_key == normalized_semantic:
            coerced_value, requires_review = coerce_for_field(user_value, expected_type, field_type)
            confidence = 0.95 if not requires_review else 0.70
            reason = f"Direct match: '{user_key}' matches semantic '{semantic_meaning}'"
            return user_key, coerced_value, confidence, reason, requires_review

    for user_key, user_value in user_data.items():
        normalized_key = normalize_key(user_key)
        if normalized_key in equivalence:
            coerced_value, requires_review = coerce_for_field(user_value, expected_type, field_type)
            confidence = 0.90 if not requires_review else 0.65
            reason = f"Alias match: '{user_key}' matches semantic '{semantic_meaning}' via alias cluster"
            return user_key, coerced_value, confidence, reason, requires_review

    return None, None, 0.0, "No deterministic match found", False


MAX_AI_REASON_CHARS = 200


def _parse_fallback_entry(entry: Any, user_data: dict[str, Any]) -> tuple[str, float, str] | None:
    """Validate one model answer; anything off-shape is dropped, never trusted.

    Requires an existing user key and a numeric confidence in [0, 1]. The
    model's reason is untrusted text: kept only as a short string.
    """
    if not isinstance(entry, dict):
        return None
    key, confidence, reason = entry.get("matched_key"), entry.get("confidence"), entry.get("reason")
    if not isinstance(key, str) or key not in user_data:
        return None
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
        return None
    if not isinstance(reason, str) or not reason.strip():
        reason = "Fallback mapping"
    return key, float(confidence), reason[:MAX_AI_REASON_CHARS]


def semantic_fallback_mapping(
    unmapped_fields: list[EnrichedFormField],
    user_data: dict[str, Any],
) -> dict[str, tuple[str, str | None, float, str]]:
    """
    AI key fallback: ask the model which user key each unresolved field should get.

    Only key names and value *types* are sent to the provider — never raw values.
    """
    if not unmapped_fields:
        return {}

    client = SemanticClient()
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
                "You are a data mapping assistant. Map form fields to user data keys. Return ONLY valid JSON."
            ),
            user_prompt=prompt,
            temperature=0.2,
        )
        fallback_result = json.loads(strip_json_code_fence(content))
        if not isinstance(fallback_result, dict):
            raise ValueError("fallback response is not a JSON object")

        result: dict[str, tuple[str, str | None, float, str]] = {}
        for field in unmapped_fields:
            parsed = _parse_fallback_entry(fallback_result.get(field.field.name), user_data)
            if parsed is None:
                continue
            matched_key, confidence, reason = parsed
            coerced_value, _ = coerce_for_field(
                user_data[matched_key],
                field.semantics.expected_data_type,
                field.field.field_type,
            )
            result[field.field.name] = (matched_key, coerced_value, confidence, reason)
        return result
    except (RuntimeError, json.JSONDecodeError, TypeError, ValueError, KeyError) as exc:
        logger.warning("AI key fallback failed: %s", exc)
        return {}


def map_user_data_to_fields(
    enriched_fields: list[EnrichedFormField],
    user_data: dict[str, Any],
    *,
    strict: bool = False,
    allow_fallback_mapping: bool = False,
    registry: AliasRegistry | None = None,
    use_semantic_inference: bool = False,
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
    flat = flatten_user_data(user_data)

    # Pass 1: user keys that address a field by its full path claim it, so the
    # same value cannot also fill a sibling field through a leaf or alias
    # (``applicant.name`` must not fill ``spouse.name``).
    # index -> (matched user key, full match tuple)
    matches: dict[int, tuple[str, tuple[str | None, str | None, float, str, bool]]] = {}
    for index, enriched_field in enumerate(enriched_fields):
        match = match_field_name(
            enriched_field.field.name,
            flat.values,
            enriched_field.semantics.expected_data_type,
            enriched_field.field.field_type,
        )
        if match[0]:
            matches[index] = (match[0], match)
    claimed = {key for key, _ in matches.values()}
    ai_assisted: set[int] = set()
    candidates = {
        key: value for key, value in flat.candidates().items() if flat.source_key(key) not in claimed
    }

    # Pass 2: everything else matches by name, semantic or alias.
    for index, enriched_field in enumerate(enriched_fields):
        if index in matches:
            continue
        semantics = enriched_field.semantics
        match = match_field_name(
            enriched_field.field.name,
            candidates,
            semantics.expected_data_type,
            enriched_field.field.field_type,
        )
        if not match[0]:
            # Semantic and alias matching depend on the field's semantics, which
            # the AI model may have supplied.
            match = find_deterministic_match(
                semantics.semantic_meaning,
                candidates,
                semantics.expected_data_type,
                registry=active,
                field_type=enriched_field.field.field_type,
            )
            if match[0] and enriched_field.ai_inferred:
                key, value, confidence, reason, review = match
                match = (key, value, min(confidence, semantics.confidence_score), f"AI: {reason}", review)
                ai_assisted.add(index)
        if match[0]:
            matches[index] = (match[0], match)

    for index, enriched_field in enumerate(enriched_fields):
        if index not in matches:
            unmapped_fields.append(enriched_field)
            continue
        matched_key, (_, matched_value, confidence, reason, requires_review) = matches[index]
        source = flat.source_key(matched_key)
        used_user_keys.add(source)
        if source != matched_key:
            reason = f"{reason} (from '{source}')"
        decisions.append(
            FieldMappingDecision(
                field_name=enriched_field.field.name,
                semantic_meaning=enriched_field.semantics.semantic_meaning,
                selected_value=matched_value,
                confidence=confidence,
                reason=reason,
                requires_review=requires_review or confidence < 0.80,
                ai_assisted=index in ai_assisted,
            )
        )

    if not strict and allow_fallback_mapping and unmapped_fields:
        high_value_fields = [
            f for f in unmapped_fields if f.field.required or f.semantics.confidence_score > 0.8
        ]

        if high_value_fields:
            fallback_mappings = semantic_fallback_mapping(high_value_fields, flat.values)

            for enriched_field in high_value_fields[:]:
                field_name = enriched_field.field.name
                if field_name not in fallback_mappings:
                    continue
                matched_key, matched_value, confidence, reason = fallback_mappings[field_name]
                if matched_key and matched_key not in used_user_keys:
                    used_user_keys.add(matched_key)
                    # matched_value is already coerced in semantic_fallback_mapping.
                    decisions.append(
                        FieldMappingDecision(
                            field_name=field_name,
                            semantic_meaning=enriched_field.semantics.semantic_meaning,
                            selected_value=matched_value,
                            confidence=confidence,
                            reason=f"AI: {reason}",
                            requires_review=confidence < 0.80,
                            ai_assisted=True,
                        )
                    )
                    unmapped_fields.remove(enriched_field)

    missing_required = [f.field.name for f in unmapped_fields if f.field.required]
    unmapped_user_keys = [key for key in flat.values if key not in used_user_keys]
    all_names = [f.field.name for f in enriched_fields]
    unmatched_opaque = [f.field.name for f in unmapped_fields]

    return MappingResult(
        decisions=decisions,
        missing_required=missing_required,
        unmapped_user_keys=unmapped_user_keys,
        mapping_hints=opaque_mapping_hints(
            all_names,
            unmatched_opaque=unmatched_opaque,
            use_semantic_inference=use_semantic_inference,
        ),
    )
