"""Behavioral tests for deterministic and fallback mapping paths."""

import pytest

from pdf_autofiller import mapping as mapping_module
from pdf_autofiller.mapping import (
    coerce_value,
    find_deterministic_match,
    map_user_data_to_fields,
    normalize_key,
    semantic_fallback_mapping,
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

    matched_key, matched_value, confidence, reason, _requires_review = find_deterministic_match(
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

    matched_key, matched_value, confidence, reason, _requires_review = find_deterministic_match(
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

    matched_key, matched_value, confidence, _reason, _requires_review = find_deterministic_match(
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


def test_semantic_fallback_mapping_returns_empty_on_client_error(monkeypatch):
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
        def __init__(self, api_key=None, usage=None):
            del api_key, usage

        @staticmethod
        def is_available():
            return True

        @staticmethod
        def create_json_completion(**_kwargs):
            raise RuntimeError("provider failure")

    monkeypatch.setattr(mapping_module, "SemanticClient", BrokenClient)
    result = semantic_fallback_mapping(fields, {"dob": "1990-01-15"})

    assert result == {}


def test_semantic_fallback_mapping_parses_markdown_and_coerces_values(monkeypatch):
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
        def __init__(self, api_key=None, usage=None):
            del api_key, usage

        @staticmethod
        def is_available():
            return True

        @staticmethod
        def create_json_completion(**_kwargs):
            return """```json
{"txtConsent":{"matched_key":"agree","confidence":0.88,"reason":"Matched consent"}}
```"""

    monkeypatch.setattr(mapping_module, "SemanticClient", GoodClient)
    result = semantic_fallback_mapping(fields, {"agree": "yes"})

    assert "txtConsent" in result
    matched_key, matched_value, confidence, reason, requires_review = result["txtConsent"]
    assert matched_key == "agree"
    assert matched_value == "true"
    # The model claimed 0.88; self-reported confidence is capped so it cannot
    # clear the review gate on its own.
    assert confidence == mapping_module.MODEL_CONFIDENCE_CEILING
    assert confidence < mapping_module.MAPPING_REVIEW_THRESHOLD
    assert reason == "Matched consent"
    assert requires_review is False


def test_semantic_fallback_prompt_includes_keys_beyond_preview_limit(monkeypatch):
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
        def __init__(self, api_key=None, usage=None):
            del api_key, usage

        @staticmethod
        def is_available():
            return True

        @staticmethod
        def create_json_completion(**kwargs):
            captured_prompt["user_prompt"] = kwargs["user_prompt"]
            return '{"txtExtra":{"matched_key":null,"confidence":0.0,"reason":"No match"}}'

    monkeypatch.setattr(mapping_module, "SemanticClient", RecordingClient)
    semantic_fallback_mapping(
        fields,
        {f"extra_{index}": f"value_{index}" for index in range(11)},
    )

    assert '"extra_10"' in captured_prompt["user_prompt"]


def test_semantic_fallback_prompt_withholds_raw_user_values(monkeypatch):
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
        def __init__(self, api_key=None, usage=None):
            del api_key, usage

        @staticmethod
        def is_available():
            return True

        @staticmethod
        def create_json_completion(**kwargs):
            captured_prompt["user_prompt"] = kwargs["user_prompt"]
            return '{"txtName":{"matched_key":null,"confidence":0.0,"reason":"No match"}}'

    monkeypatch.setattr(mapping_module, "SemanticClient", RecordingClient)
    semantic_fallback_mapping(fields, {"firstname": "TopSecretValue"})

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
    matched_key, matched_value, confidence, reason, _requires_review = find_deterministic_match(
        semantic_meaning,
        {user_key: user_value},
        "string",
    )

    assert matched_key == user_key
    assert matched_value == user_value
    assert confidence >= 0.85
    assert "Alias match" in reason


def test_community_w9_alias_pack_loaded():
    """W-9 alias pack extends matching for tax form field names."""
    matched_key, matched_value, confidence, reason, _requires_review = find_deterministic_match(
        "taxpayer_name",
        {"name_line_1": "Jane Doe"},
        "string",
    )
    assert matched_key == "name_line_1"
    assert matched_value == "Jane Doe"
    assert confidence >= 0.85
    assert "Alias match" in reason



def _fallback_client(payload: str):
    """Fake SemanticClient returning a canned fallback-mapping response."""

    class FakeClient:
        def __init__(self, api_key=None, usage=None):
            del api_key, usage

        @staticmethod
        def is_available():
            return True

        @staticmethod
        def create_json_completion(**_kwargs):
            return payload

    return FakeClient


def test_map_user_data_defaults_match_the_http_api(monkeypatch):
    """The SDK must not enable the model path when the API would not.

    Library and API defaults previously disagreed, so importing the function
    turned on provider-backed mapping that an HTTP caller had to opt into.
    """

    class ForbiddenClient:
        def __init__(self, api_key=None, usage=None):
            raise AssertionError("fallback mapping must be opt-in")

    monkeypatch.setattr(mapping_module, "SemanticClient", ForbiddenClient)

    fields = [
        EnrichedFormField(
            field=FormField(
                name="txtMystery", field_type="text", required=True, page_number=1
            ),
            semantics=FieldSemantics(
                semantic_meaning="mystery_field",
                expected_data_type="string",
                confidence_score=0.95,
            ),
        )
    ]

    result = map_user_data_to_fields(fields, {"something": "value"})
    assert result.missing_required == ["txtMystery"]


def test_model_confidence_is_capped_below_the_review_threshold(monkeypatch):
    """A model asserting near-certainty about its own guess is not evidence."""
    monkeypatch.setattr(
        mapping_module,
        "SemanticClient",
        _fallback_client(
            '{"txtMystery":{"matched_key":"opaque_source_key","confidence":0.99,'
            '"reason":"model says so"}}'
        ),
    )

    fields = [
        EnrichedFormField(
            field=FormField(
                name="txtMystery", field_type="text", required=False, page_number=1
            ),
            semantics=FieldSemantics(
                semantic_meaning="mystery_field",
                expected_data_type="string",
                confidence_score=0.95,
            ),
        )
    ]

    # The key deliberately does not match the semantic name, so only the
    # provider fallback can resolve this field.
    result = map_user_data_to_fields(
        fields,
        {"opaque_source_key": "value"},
        strict=False,
        allow_fallback_mapping=True,
    )

    decision = next(d for d in result.decisions if d.field_name == "txtMystery")
    assert decision.confidence_source == "model"
    assert decision.confidence == mapping_module.MODEL_CONFIDENCE_CEILING
    assert decision.requires_review is True


def test_deterministic_decisions_record_their_confidence_source(
    sample_enriched_fields,
):
    result = map_user_data_to_fields(
        sample_enriched_fields, {"firstname": "John"}, strict=True
    )
    decision = next(d for d in result.decisions if d.field_name == "txtFirstName")
    assert decision.confidence_source == "deterministic"
    assert decision.requires_review is False


def test_clamp_model_confidence_bounds_both_ends():
    assert mapping_module.clamp_model_confidence(1.0) == mapping_module.MODEL_CONFIDENCE_CEILING
    assert mapping_module.clamp_model_confidence(-5.0) == 0.0
    assert mapping_module.clamp_model_confidence(0.1) == pytest.approx(0.1)


def test_fallback_ignores_keys_the_caller_never_supplied(monkeypatch):
    """A response cannot invent a source key for a field."""
    monkeypatch.setattr(
        mapping_module,
        "SemanticClient",
        _fallback_client(
            '{"txtMystery":{"matched_key":"not_a_real_key","confidence":0.9,'
            '"reason":"hallucinated"}}'
        ),
    )

    fields = [
        EnrichedFormField(
            field=FormField(
                name="txtMystery", field_type="text", required=False, page_number=1
            ),
            semantics=FieldSemantics(
                semantic_meaning="mystery_field",
                expected_data_type="string",
                confidence_score=0.95,
            ),
        )
    ]

    result = semantic_fallback_mapping(fields, {"real_key": "value"})
    assert result == {}


def test_fallback_coerces_each_value_exactly_once(monkeypatch):
    """Double coercion previously discarded the ambiguity flag on first pass."""
    monkeypatch.setattr(
        mapping_module,
        "SemanticClient",
        _fallback_client(
            '{"txtWhen":{"matched_key":"opaque_date_key","confidence":0.9,'
            '"reason":"date-ish"}}'
        ),
    )

    fields = [
        EnrichedFormField(
            field=FormField(
                name="txtWhen", field_type="text", required=False, page_number=1
            ),
            semantics=FieldSemantics(
                semantic_meaning="when",
                expected_data_type="date",
                confidence_score=0.95,
            ),
        )
    ]

    result = map_user_data_to_fields(
        fields,
        {"opaque_date_key": "05/15/1990"},
        strict=False,
        allow_fallback_mapping=True,
    )

    decision = next(d for d in result.decisions if d.field_name == "txtWhen")
    # The non-ISO date is preserved verbatim and flagged, not silently reshaped.
    assert decision.selected_value == "05/15/1990"
    assert decision.requires_review is True


def test_fallback_records_degradation_when_provider_unavailable():
    from pdf_autofiller.provider_config import ProviderUsage

    fields = [
        EnrichedFormField(
            field=FormField(
                name="txtMystery", field_type="text", required=False, page_number=1
            ),
            semantics=FieldSemantics(
                semantic_meaning="mystery_field",
                expected_data_type="string",
                confidence_score=0.95,
            ),
        )
    ]
    usage = ProviderUsage()
    assert semantic_fallback_mapping(fields, {"a": "b"}, usage=usage) == {}
    assert "provider_unavailable" in usage.degraded_reasons


def test_fallback_prompt_marks_document_text_as_untrusted(monkeypatch):
    captured: dict[str, str] = {}

    class RecordingClient:
        def __init__(self, api_key=None, usage=None):
            del api_key, usage

        @staticmethod
        def is_available():
            return True

        @staticmethod
        def create_json_completion(**kwargs):
            captured["user_prompt"] = kwargs["user_prompt"]
            captured["system_prompt"] = kwargs["system_prompt"]
            return "{}"

    monkeypatch.setattr(mapping_module, "SemanticClient", RecordingClient)

    fields = [
        EnrichedFormField(
            field=FormField(
                name="txtMystery", field_type="text", required=False, page_number=1
            ),
            semantics=FieldSemantics(
                semantic_meaning="mystery_field",
                expected_data_type="string",
                confidence_score=0.95,
            ),
        )
    ]
    semantic_fallback_mapping(fields, {"a": "b"})

    assert "untrusted" in captured["user_prompt"].lower()
    assert "UNTRUSTED DATA" in captured["system_prompt"]
