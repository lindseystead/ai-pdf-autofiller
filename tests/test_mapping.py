"""Behavioral tests for deterministic and fallback mapping paths."""

import pytest

from pdf_autofiller import mapping as mapping_module
from pdf_autofiller.mapping import (
    coerce_value,
    find_deterministic_match,
    semantic_fallback_mapping,
    map_user_data_to_fields,
    normalize_key,
)
from pdf_autofiller.models import (
    EnrichedFormField,
    FieldSemantics,
    FormField,
)


@pytest.fixture
def sample_enriched_fields():
    """Representative form fields used across mapping tests."""
    return [
        EnrichedFormField(
            field=FormField(
                name="txtFirstName",
                field_type="text",
                required=True,
                page_number=1
            ),
            semantics=FieldSemantics(
                semantic_meaning="first_name",
                expected_data_type="string",
                confidence_score=0.95
            )
        ),
        EnrichedFormField(
            field=FormField(
                name="txtLastName",
                field_type="text",
                required=True,
                page_number=1
            ),
            semantics=FieldSemantics(
                semantic_meaning="last_name",
                expected_data_type="string",
                confidence_score=0.95
            )
        ),
        EnrichedFormField(
            field=FormField(
                name="txtDOB",
                field_type="text",
                required=True,
                page_number=1
            ),
            semantics=FieldSemantics(
                semantic_meaning="date_of_birth",
                expected_data_type="date",
                confidence_score=0.90
            )
        ),
        EnrichedFormField(
            field=FormField(
                name="txtEmail",
                field_type="text",
                required=False,
                page_number=1
            ),
            semantics=FieldSemantics(
                semantic_meaning="email_address",
                expected_data_type="string",
                confidence_score=0.88
            )
        ),
    ]


def test_normalize_key():
    """Test key normalization."""
    assert normalize_key("First-Name!") == "first_name"
    assert normalize_key("Email Address") == "email_address"
    assert normalize_key("phone_number") == "phone_number"
    assert normalize_key("DOB") == "dob"
    assert normalize_key("first__name") == "first_name"


def test_coerce_value_string():
    """Test value coercion for string type."""
    value, requires_review = coerce_value("John", "string")
    assert value == "John"
    assert requires_review is False


def test_coerce_value_date():
    """Test value coercion for date type."""
    value, requires_review = coerce_value("2024-01-15", "date")
    assert value == "2024-01-15"
    assert requires_review is False

    value, requires_review = coerce_value("01/15/2024", "date")
    assert value == "01/15/2024"
    assert requires_review is True


def test_coerce_value_number():
    """Test value coercion for number type."""
    value, requires_review = coerce_value("123", "number")
    assert value == "123"
    assert requires_review is False

    value, requires_review = coerce_value("123.45", "number")
    assert value == "123.45"
    assert requires_review is False

    value, requires_review = coerce_value("abc", "number")
    assert value == "abc"
    assert requires_review is True


def test_coerce_value_boolean():
    """Test value coercion for boolean type."""
    value, requires_review = coerce_value("true", "boolean")
    assert value == "true"
    assert requires_review is False

    value, requires_review = coerce_value("yes", "boolean")
    assert value == "true"
    assert requires_review is False

    value, requires_review = coerce_value("false", "boolean")
    assert value == "false"
    assert requires_review is False

    value, requires_review = coerce_value("maybe", "boolean")
    assert value == "maybe"
    assert requires_review is True


def test_find_deterministic_match_direct():
    """Test deterministic matching with direct match."""
    user_data = {"first_name": "John", "lastname": "Doe"}
    
    matched_key, matched_value, confidence, reason = find_deterministic_match(
        "first_name",
        user_data,
        "string"
    )
    
    assert matched_key == "first_name"
    assert matched_value == "John"
    assert confidence >= 0.90
    assert "Direct match" in reason or "direct" in reason.lower()


def test_find_deterministic_match_alias():
    """Test deterministic matching with alias match."""
    user_data = {"surname": "Smith", "email": "test@example.com"}
    
    matched_key, matched_value, confidence, reason = find_deterministic_match(
        "last_name",
        user_data,
        "string"
    )
    
    assert matched_key == "surname"
    assert matched_value == "Smith"
    assert confidence >= 0.85
    assert "Alias match" in reason


def test_find_deterministic_match_no_match():
    """Test deterministic matching when no match found."""
    user_data = {"unrelated": "value"}
    
    matched_key, matched_value, confidence, reason = find_deterministic_match(
        "first_name",
        user_data,
        "string"
    )
    
    assert matched_key is None
    assert matched_value is None
    assert confidence == 0.0


def test_map_user_data_to_fields_success(sample_enriched_fields):
    """Test successful mapping with deterministic matching."""
    user_data = {
        "firstname": "John",
        "lastname": "Doe",
        "dob": "1990-05-15",
        "email": "john@example.com"
    }
    
    result = map_user_data_to_fields(
        sample_enriched_fields,
        user_data,
        strict=True
    )
    
    assert len(result.decisions) == 4
    assert len(result.missing_required) == 0

    first_name_decision = next(d for d in result.decisions if d.field_name == "txtFirstName")
    assert first_name_decision.selected_value == "John"
    assert first_name_decision.confidence >= 0.90

    dob_decision = next(d for d in result.decisions if d.field_name == "txtDOB")
    assert dob_decision.selected_value == "1990-05-15"
    assert dob_decision.requires_review is False


def test_map_user_data_to_fields_missing_required(sample_enriched_fields):
    """Test mapping with missing required field."""
    user_data = {
        "firstname": "John",
        "email": "john@example.com"
    }
    
    result = map_user_data_to_fields(
        sample_enriched_fields,
        user_data,
        strict=True
    )
    
    assert len(result.decisions) == 2

    assert len(result.missing_required) == 2
    assert "txtLastName" in result.missing_required
    assert "txtDOB" in result.missing_required


def test_map_user_data_to_fields_ambiguous_requires_review(sample_enriched_fields):
    """Test mapping with ambiguous value that requires review."""
    user_data = {
        "firstname": "John",
        "lastname": "Doe",
        "dob": "05/15/1990",
        "email": "john@example.com"
    }
    
    result = map_user_data_to_fields(
        sample_enriched_fields,
        user_data,
        strict=True
    )
    
    assert len(result.decisions) == 4

    dob_decision = next(d for d in result.decisions if d.field_name == "txtDOB")
    assert dob_decision.requires_review is True
    assert dob_decision.selected_value == "05/15/1990"


def test_map_user_data_to_fields_unmapped_keys(sample_enriched_fields):
    """Test mapping with unmapped user data keys."""
    user_data = {
        "firstname": "John",
        "lastname": "Doe",
        "dob": "1990-05-15",
        "unused_key": "unused_value",
        "another_unused": "value"
    }
    
    result = map_user_data_to_fields(
        sample_enriched_fields,
        user_data,
        strict=True
    )
    
    assert len(result.unmapped_user_keys) == 2
    assert "unused_key" in result.unmapped_user_keys
    assert "another_unused" in result.unmapped_user_keys


def test_map_user_data_to_fields_normalized_matching(sample_enriched_fields):
    """Test that normalization handles various key formats."""
    user_data = {
        "First-Name": "John",
        "Last Name": "Doe",
        "DOB": "1990-05-15",
        "Email_Address": "john@example.com"
    }
    
    result = map_user_data_to_fields(
        sample_enriched_fields,
        user_data,
        strict=True
    )
    
    assert len(result.decisions) == 4
    assert len(result.missing_required) == 0

    first_name_decision = next(d for d in result.decisions if d.field_name == "txtFirstName")
    assert first_name_decision.selected_value == "John"


def test_semantic_fallback_mapping_returns_empty_on_client_error():
    fields = [
        EnrichedFormField(
            field=FormField(name="txtDOB", field_type="text", required=True, page_number=1),
            semantics=FieldSemantics(
                semantic_meaning="date_of_birth",
                expected_data_type="date",
                confidence_score=0.9,
            ),
        )
    ]

    class BrokenClient:
        def __init__(self, api_key=None):
            del api_key

        @staticmethod
        def is_available():
            return True

        @staticmethod
        def create_json_completion(**_kwargs):
            raise RuntimeError("provider failure")

    original_client = mapping_module.SemanticClient
    mapping_module.SemanticClient = BrokenClient
    try:
        result = semantic_fallback_mapping(fields, {"dob": "1990-01-15"})
    finally:
        mapping_module.SemanticClient = original_client

    assert result == {}


def test_semantic_fallback_mapping_parses_markdown_and_coerces_values():
    fields = [
        EnrichedFormField(
            field=FormField(name="txtConsent", field_type="text", required=False, page_number=1),
            semantics=FieldSemantics(
                semantic_meaning="consent",
                expected_data_type="boolean",
                confidence_score=0.95,
            ),
        )
    ]

    class GoodClient:
        def __init__(self, api_key=None):
            del api_key

        @staticmethod
        def is_available():
            return True

        @staticmethod
        def create_json_completion(**_kwargs):
            return """```json
{"txtConsent":{"matched_key":"agree","confidence":0.88,"reason":"Matched consent"}}
```"""

    original_client = mapping_module.SemanticClient
    mapping_module.SemanticClient = GoodClient
    try:
        result = semantic_fallback_mapping(fields, {"agree": "yes"})
    finally:
        mapping_module.SemanticClient = original_client

    assert "txtConsent" in result
    matched_key, matched_value, confidence, reason = result["txtConsent"]
    assert matched_key == "agree"
    assert matched_value == "true"
    assert confidence == 0.88
    assert reason == "Matched consent"


def test_semantic_fallback_prompt_includes_keys_beyond_preview_limit():
    fields = [
        EnrichedFormField(
            field=FormField(name="txtExtra", field_type="text", required=False, page_number=1),
            semantics=FieldSemantics(
                semantic_meaning="extra_field",
                expected_data_type="string",
                confidence_score=0.95,
            ),
        )
    ]
    captured_prompt: dict[str, str] = {}

    class RecordingClient:
        def __init__(self, api_key=None):
            del api_key

        @staticmethod
        def is_available():
            return True

        @staticmethod
        def create_json_completion(**kwargs):
            captured_prompt["user_prompt"] = kwargs["user_prompt"]
            return '{"txtExtra":{"matched_key":null,"confidence":0.0,"reason":"No match"}}'

    original_client = mapping_module.SemanticClient
    mapping_module.SemanticClient = RecordingClient
    try:
        semantic_fallback_mapping(
            fields,
            {f"extra_{index}": f"value_{index}" for index in range(11)},
        )
    finally:
        mapping_module.SemanticClient = original_client

    assert '"extra_10"' in captured_prompt["user_prompt"]


def test_semantic_fallback_prompt_withholds_raw_user_values():
    fields = [
        EnrichedFormField(
            field=FormField(name="txtName", field_type="text", required=False, page_number=1),
            semantics=FieldSemantics(
                semantic_meaning="first_name",
                expected_data_type="string",
                confidence_score=0.95,
            ),
        )
    ]
    captured_prompt: dict[str, str] = {}

    class RecordingClient:
        def __init__(self, api_key=None):
            del api_key

        @staticmethod
        def is_available():
            return True

        @staticmethod
        def create_json_completion(**kwargs):
            captured_prompt["user_prompt"] = kwargs["user_prompt"]
            return '{"txtName":{"matched_key":null,"confidence":0.0,"reason":"No match"}}'

    original_client = mapping_module.SemanticClient
    mapping_module.SemanticClient = RecordingClient
    try:
        semantic_fallback_mapping(fields, {"firstname": "TopSecretValue"})
    finally:
        mapping_module.SemanticClient = original_client

    prompt = captured_prompt["user_prompt"]
    # Key names and value types are shared; raw PII values are not.
    assert "firstname" in prompt
    assert "str" in prompt
    assert "TopSecretValue" not in prompt


@pytest.mark.parametrize(
    ("semantic_meaning", "user_key", "user_value"),
    [
        ("street_address", "addr1", "123 Main St"),
        ("city", "town", "Springfield"),
        ("state", "province", "IL"),
        ("postal_code", "zipcode", "62701"),
        ("social_security_number", "ssn", "123-45-6789"),
        ("employer", "company", "Acme Corp"),
        ("job_title", "position", "Engineer"),
    ],
)
def test_find_deterministic_match_expanded_aliases(
    semantic_meaning: str,
    user_key: str,
    user_value: str,
):
    """Expanded alias vocabulary covers common intake and HR form fields."""
    matched_key, matched_value, confidence, reason = find_deterministic_match(
        semantic_meaning,
        {user_key: user_value},
        "string",
    )

    assert matched_key == user_key
    assert matched_value == user_value
    assert confidence >= 0.85
    assert "Alias match" in reason

