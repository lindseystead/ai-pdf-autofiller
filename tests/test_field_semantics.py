"""Tests for the semantic provider client: prompts, response parsing, failure modes."""

import json
import logging

import pytest

from pdf_autofiller import field_semantics
from pdf_autofiller.models import FormField


def sample_field(name: str = "txtFirstName", value: str | None = None) -> FormField:
    return FormField(name=name, field_type="text", value=value, required=True, page_number=1)


def _fake_client(content: str, calls: list[dict] | None = None):
    """Stand-in for the OpenAI client that returns ``content`` from chat completions."""

    class Completions:
        @staticmethod
        def create(**kwargs):
            if calls is not None:
                calls.append(kwargs)
            message = type("Message", (), {"content": content})()
            return type("Response", (), {"choices": [type("Choice", (), {"message": message})()]})()

    return type("Client", (), {"chat": type("Chat", (), {"completions": Completions()})()})()


def _client_returning(content: str, calls: list[dict] | None = None) -> field_semantics.SemanticClient:
    client = field_semantics.SemanticClient(api_key=None)
    client._client = _fake_client(content, calls)
    return client


def _batch(**fields: dict) -> str:
    return json.dumps({"fields": fields})


FIRST_NAME = {"semantic_meaning": "first_name", "expected_data_type": "string", "confidence_score": 0.9}


def test_semantic_client_unavailable_without_key(monkeypatch):
    monkeypatch.setattr(field_semantics, "PROVIDER_SDK_AVAILABLE", False)
    monkeypatch.delenv("MODEL_PROVIDER_API_KEY", raising=False)
    assert field_semantics.SemanticClient().is_available() is False


def test_batch_prompt_includes_field_and_page_context():
    client = field_semantics.SemanticClient(api_key=None)
    prompt = client._build_batch_prompt([sample_field()], page_context={1: "context here"})
    assert "txtFirstName" in prompt
    assert "context here" in prompt
    assert "expected_data_type" in prompt


def test_batch_prompt_never_contains_existing_field_values():
    client = field_semantics.SemanticClient(api_key=None)
    fields = [sample_field("txtSSN", value="123-45-6789"), sample_field("txtName", value="Jane Doe")]
    prompt = client._build_batch_prompt(fields)
    assert "123-45-6789" not in prompt
    assert "Jane Doe" not in prompt
    assert prompt.count('"has_value": true') == 2


def test_infer_semantics_batch_is_a_single_provider_call():
    calls: list[dict] = []
    client = _client_returning(_batch(txtFirstName=FIRST_NAME, txtLastName=FIRST_NAME), calls)
    result = client.infer_semantics_batch([sample_field(), sample_field("txtLastName")])
    assert len(calls) == 1
    assert set(result) == {"txtFirstName", "txtLastName"}


def test_infer_semantics_batch_raises_when_client_unavailable():
    client = field_semantics.SemanticClient(api_key=None)
    with pytest.raises(RuntimeError, match="not available"):
        client.infer_semantics_batch([sample_field()])


def test_parse_batch_response_ignores_fields_that_were_not_asked_about():
    client = field_semantics.SemanticClient(api_key=None)
    raw = _batch(txtFirstName=FIRST_NAME, txtInjected=FIRST_NAME)
    parsed = client._parse_batch_response(raw, expected_names={"txtFirstName", "other"})
    assert set(parsed) == {"txtFirstName"}


def test_parse_batch_response_accepts_code_fence():
    client = field_semantics.SemanticClient(api_key=None)
    raw = f"```json\n{_batch(txtFirstName=FIRST_NAME)}\n```"
    assert (
        client._parse_batch_response(raw, expected_names={"txtFirstName"})["txtFirstName"].confidence_score
        == 0.9
    )


@pytest.mark.parametrize("raw", ["{not-valid-json}", "", "[]", '{"unexpected": 1}', "null"])
def test_parse_batch_response_rejects_malformed_output(raw):
    client = field_semantics.SemanticClient(api_key=None)
    with pytest.raises(ValueError):
        client._parse_batch_response(raw, expected_names={"txtFirstName"})


@pytest.mark.parametrize(
    "bad",
    [
        {"semantic_meaning": "x", "expected_data_type": "not_a_type", "confidence_score": 0.5},
        {"semantic_meaning": "x", "expected_data_type": "string", "confidence_score": 7},
        {"semantic_meaning": "x"},
        "first_name",
    ],
)
def test_parse_batch_response_drops_invalid_entries_and_keeps_valid_ones(bad, caplog):
    client = field_semantics.SemanticClient(api_key=None)
    raw = json.dumps({"fields": {"txtFirstName": FIRST_NAME, "txtBad": bad}})
    with caplog.at_level(logging.WARNING):
        parsed = client._parse_batch_response(raw, expected_names={"txtFirstName", "txtBad"})
    assert set(parsed) == {"txtFirstName"}


def test_infer_semantics_batch_surfaces_unparseable_output():
    client = _client_returning("{not-json}")
    with pytest.raises(ValueError, match="Invalid JSON"):
        client.infer_semantics_batch([sample_field()])


def test_create_json_completion_raises_when_unavailable():
    client = field_semantics.SemanticClient(api_key=None)
    with pytest.raises(RuntimeError, match="not available"):
        client.create_json_completion(system_prompt="sys", user_prompt="usr")


def test_create_json_completion_returns_content():
    client = _client_returning('{"ok":true}')
    assert client.create_json_completion(system_prompt="sys", user_prompt="usr") == '{"ok":true}'


def test_provider_client_has_a_bounded_timeout_and_retries(monkeypatch):
    captured: dict = {}

    class RecordingOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(field_semantics, "PROVIDER_SDK_AVAILABLE", True)
    monkeypatch.setattr(field_semantics.provider_sdk, "OpenAI", RecordingOpenAI)
    field_semantics.SemanticClient(api_key="test-key")
    assert 0 < captured["timeout"] <= 60
    assert captured["max_retries"] <= 1


def test_every_provider_call_uses_the_configured_model():
    calls: list[dict] = []
    client = _client_returning(_batch(txtFirstName=FIRST_NAME), calls)
    client.infer_semantics_batch([sample_field()])
    client.create_json_completion(system_prompt="s", user_prompt="u")
    assert [call["model"] for call in calls] == [field_semantics.MODEL, field_semantics.MODEL]


def test_worst_case_ai_time_fits_inside_the_api_job_timeout():
    from pdf_autofiller.api import config

    calls_per_run = 2  # semantic inference + fallback mapping
    attempts = field_semantics.MAX_RETRIES + 1
    worst_case = calls_per_run * attempts * field_semantics.REQUEST_TIMEOUT_SECONDS
    assert worst_case < config.PDF_READ_TIMEOUT_SECONDS


def test_empty_provider_content_is_reported_as_such_not_as_a_provider_failure():
    client = _client_returning(None)  # the SDK can return content=None
    with pytest.raises(RuntimeError) as excinfo:
        client.create_json_completion(system_prompt="s", user_prompt="u")
    assert str(excinfo.value) == "Semantic response did not include text content"
