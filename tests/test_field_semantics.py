"""Tests for semantic response parsing and client behavior."""

import pytest

from pdf_autofiller import field_semantics
from pdf_autofiller.models import FieldSemantics, FormField


def sample_field() -> FormField:
    return FormField(
        name="txtFirstName",
        field_type="text",
        required=True,
        page_number=1,
    )


def test_semantic_client_unavailable_without_key(monkeypatch):
    monkeypatch.setattr(field_semantics, "PROVIDER_SDK_AVAILABLE", False)
    monkeypatch.delenv("MODEL_PROVIDER_API_KEY", raising=False)

    client = field_semantics.SemanticClient()
    assert client.is_available() is False


def test_build_prompt_includes_field_and_context():
    client = field_semantics.SemanticClient(api_key=None)
    prompt = client._build_prompt(sample_field(), "context here")
    assert "txtFirstName" in prompt
    assert "context here" in prompt
    assert "expected_data_type" in prompt


def test_build_prompt_does_not_leak_field_value():
    client = field_semantics.SemanticClient(api_key=None)
    field = FormField(
        name="txtSSN",
        field_type="text",
        value="123-45-6789",
        required=True,
        page_number=1,
    )
    prompt = client._build_prompt(field, None)
    assert "123-45-6789" not in prompt
    assert "Has Value: yes" in prompt


def test_parse_response_accepts_json_and_code_fence():
    client = field_semantics.SemanticClient(api_key=None)
    raw = """
```json
{
  "semantic_meaning": "first_name",
  "expected_data_type": "string",
  "confidence_score": 0.91
}
```
"""
    parsed = client._parse_response(raw)
    assert parsed.semantic_meaning == "first_name"
    assert parsed.expected_data_type == "string"
    assert parsed.confidence_score == 0.91


def test_parse_response_raises_on_invalid_json():
    client = field_semantics.SemanticClient(api_key=None)
    with pytest.raises(ValueError, match="Invalid JSON"):
        client._parse_response("{not-valid-json}")


def test_parse_response_raises_on_schema_mismatch():
    client = field_semantics.SemanticClient(api_key=None)
    with pytest.raises(ValueError, match="does not match schema"):
        client._parse_response(
            '{"semantic_meaning":"x","expected_data_type":"not_a_type","confidence_score":0.5}'
        )


def test_create_json_completion_raises_when_unavailable():
    client = field_semantics.SemanticClient(api_key=None)
    with pytest.raises(RuntimeError, match="unavailable"):
        client.create_json_completion(system_prompt="sys", user_prompt="usr")


def test_create_json_completion_returns_content():
    class FakeCompletions:
        @staticmethod
        def create(**_kwargs):
            return type(
                "Resp",
                (),
                {
                    "choices": [
                        type("Choice", (), {"message": type("Msg", (), {"content": '{"ok":true}'})()})()
                    ]
                },
            )()

    fake_client = type(
        "FakeClient",
        (),
        {"chat": type("Chat", (), {"completions": FakeCompletions()})()},
    )()

    client = field_semantics.SemanticClient(api_key=None)
    client._client = fake_client

    content = client.create_json_completion(system_prompt="sys", user_prompt="usr")
    assert content == '{"ok":true}'


def test_infer_semantics_raises_when_client_unavailable():
    client = field_semantics.SemanticClient(api_key=None)
    with pytest.raises(RuntimeError, match="not available"):
        client.infer_semantics(sample_field())


def test_infer_semantics_preserves_parse_errors():
    class FakeCompletions:
        @staticmethod
        def create(**_kwargs):
            return type(
                "Resp",
                (),
                {
                    "choices": [
                        type("Choice", (), {"message": type("Msg", (), {"content": "{not-json}"})()})()
                    ]
                },
            )()

    fake_client = type(
        "FakeClient",
        (),
        {"chat": type("Chat", (), {"completions": FakeCompletions()})()},
    )()

    client = field_semantics.SemanticClient(api_key=None)
    client._client = fake_client

    with pytest.raises(ValueError, match="Invalid JSON"):
        client.infer_semantics(sample_field())


def test_infer_field_semantics_wrapper(monkeypatch):
    expected = FieldSemantics(
        semantic_meaning="first_name",
        expected_data_type="string",
        confidence_score=0.95,
    )

    def fake_infer(self, field, context_text=None):
        assert field.name == "txtFirstName"
        assert context_text == "Near applicant name"
        return expected

    monkeypatch.setattr(field_semantics.SemanticClient, "infer_semantics", fake_infer)
    enriched = field_semantics.infer_field_semantics(
        sample_field(),
        context_text="Near applicant name",
        api_key="dummy",
    )
    assert enriched.field.name == "txtFirstName"
    assert enriched.semantics.semantic_meaning == "first_name"
