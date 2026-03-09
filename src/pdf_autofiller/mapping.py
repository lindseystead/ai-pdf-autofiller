"""
Data mapping engine for PDF form filling.

Mapping is deterministic-first (normalized keys, aliases, coercion).
Provider-backed fallback is optional and only used for unresolved high-value fields.
"""

import json
import logging
import re
from datetime import datetime
from typing import Any, Optional


from .field_semantics import SemanticClient, strip_json_code_fence
from .models import (
    EnrichedFormField,
    FieldMappingDecision,
    MappingResult,
)

logger = logging.getLogger(__name__)


# Semantic aliases used by deterministic matching.
FIELD_ALIASES: dict[str, list[str]] = {
    "first_name": ["firstname", "given_name", "forename"],
    "last_name": ["lastname", "surname", "family_name"],
    "date_of_birth": ["dob", "birth_date", "birthdate"],
    "email_address": ["email", "emailaddress"],
    "phone_number": ["phone", "mobile", "cell"],
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
    key = re.sub(r'[\s\-_\.]+', '_', key)
    key = re.sub(r'[^\w_]', '', key)
    key = re.sub(r'_+', '_', key)
    key = key.strip('_')
    
    return key


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
        date_pattern = r'^\d{4}-\d{2}-\d{2}$'
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
    expected_type: str
) -> tuple[Optional[str], Optional[str], float, str]:
    """
    Find a deterministic match for a semantic meaning.
    
    Tries direct normalized matching first, then falls back to alias matching.
    Returns None if no match found. All matching is case-insensitive and
    handles key normalization.
    
    Args:
        semantic_meaning: Semantic meaning to match (e.g., "first_name")
        user_data: User-provided data dictionary
        expected_type: Expected data type for type coercion
        
    Returns:
        Tuple of (matched_key, matched_value, confidence, reason)
    """
    normalized_semantic = normalize_key(semantic_meaning)
    
    # Direct normalized match
    for user_key, user_value in user_data.items():
        normalized_key = normalize_key(user_key)
        
        if normalized_key == normalized_semantic:
            coerced_value, requires_review = coerce_value(user_value, expected_type)
            confidence = 0.95 if not requires_review else 0.70
            reason = f"Direct match: '{user_key}' matches semantic '{semantic_meaning}'"
            return user_key, coerced_value, confidence, reason
    
    # Alias match
    if semantic_meaning in FIELD_ALIASES:
        normalized_aliases = {
            normalize_key(alias) for alias in FIELD_ALIASES[semantic_meaning]
        }
        for user_key, user_value in user_data.items():
            normalized_key = normalize_key(user_key)
            
            if normalized_key in normalized_aliases:
                coerced_value, requires_review = coerce_value(user_value, expected_type)
                confidence = 0.90 if not requires_review else 0.65
                reason = f"Alias match: '{user_key}' matches semantic '{semantic_meaning}' via alias"
                return user_key, coerced_value, confidence, reason
    
    return None, None, 0.0, "No deterministic match found"


def semantic_fallback_mapping(
    unmapped_fields: list[EnrichedFormField],
    user_data: dict[str, Any],
    api_key: Optional[str] = None
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
        fields_info.append({
            "field_name": field.field.name,
            "semantic_meaning": field.semantics.semantic_meaning,
            "expected_type": field.semantics.expected_data_type,
            "required": field.field.required
        })
    
    user_data_keys = list(user_data.keys())
    user_data_preview = {
        key: str(user_data[key])[:50]
        for key in user_data_keys[:10]
    }
    
    prompt = f"""Map the following PDF form fields to user data keys.

Form Fields:
{json.dumps(fields_info, indent=2)}

Available User Data Keys:
{json.dumps(user_data_keys, indent=2)}

Sample User Data Values (subset for context):
{json.dumps(user_data_preview, indent=2)}

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
                        user_data[matched_key],
                        field.semantics.expected_data_type
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
    allow_fallback_mapping: bool = True,
    api_key: Optional[str] = None
) -> MappingResult:
    """
    Map user-provided structured data to PDF form fields.
    
    Uses deterministic matching first (exact/normalized/aliases), then optional
    fallback mapping for ambiguous cases.
    
    Args:
        enriched_fields: List of form fields with inferred semantics
        user_data: User-provided data dictionary
        strict: If True, only use deterministic matching (no fallback mapping)
        allow_fallback_mapping: If True, use fallback mapping for unmapped required/high-value fields
        api_key: Optional provider API key for fallback mapping
        
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
    decisions: list[FieldMappingDecision] = []
    unmapped_fields: list[EnrichedFormField] = []
    used_user_keys: set[str] = set()
    
    # Deterministic pass runs first so mappings stay auditable and predictable.
    for enriched_field in enriched_fields:
        semantic = enriched_field.semantics.semantic_meaning
        expected_type = enriched_field.semantics.expected_data_type
        
        matched_key, matched_value, confidence, reason = find_deterministic_match(
            semantic,
            user_data,
            expected_type
        )
        
        if matched_key:
            used_user_keys.add(matched_key)
            coerced_value, requires_review = coerce_value(matched_value, expected_type)
            
            decisions.append(FieldMappingDecision(
                field_name=enriched_field.field.name,
                semantic_meaning=semantic,
                selected_value=coerced_value,
                confidence=confidence,
                reason=reason,
                requires_review=requires_review or confidence < 0.80
            ))
        else:
            unmapped_fields.append(enriched_field)
    
    # Provider-backed fallback is constrained to unresolved fields with high value
    # (required or high-confidence semantics).
    if not strict and allow_fallback_mapping and unmapped_fields:
        high_value_fields = [
            f for f in unmapped_fields
            if f.field.required or f.semantics.confidence_score > 0.8
        ]
        
        if high_value_fields:
            fallback_mappings = semantic_fallback_mapping(high_value_fields, user_data, api_key)
            
            for enriched_field in high_value_fields[:]:
                field_name = enriched_field.field.name
                
                if field_name in fallback_mappings:
                    matched_key, matched_value, confidence, reason = fallback_mappings[field_name]
                    
                    if matched_key and matched_key not in used_user_keys:
                        used_user_keys.add(matched_key)
                        coerced_value, requires_review = coerce_value(matched_value, enriched_field.semantics.expected_data_type)
                        
                        decisions.append(FieldMappingDecision(
                            field_name=field_name,
                            semantic_meaning=enriched_field.semantics.semantic_meaning,
                            selected_value=coerced_value,
                            confidence=confidence,
                            reason=reason,
                            requires_review=requires_review or confidence < 0.80
                        ))
                        
                        unmapped_fields.remove(enriched_field)
    
    # Collect validation results
    missing_required = [
        f.field.name
        for f in unmapped_fields
        if f.field.required
    ]
    
    unmapped_user_keys = [
        key for key in user_data.keys()
        if key not in used_user_keys
    ]
    
    return MappingResult(
        decisions=decisions,
        missing_required=missing_required,
        unmapped_user_keys=unmapped_user_keys
    )
