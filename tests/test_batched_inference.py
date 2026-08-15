"""
Tests for batched semantic inference, its cache, and provider resilience.

The behaviour under test is that one form costs one provider call, that bad or
hallucinated provider output degrades to the deterministic fallback rather than
failing the request, and that no user value ever reaches the provider.
"""

from __future__ import annotations

import json

import pytest

from pdf_autofiller import field_semantics
from pdf_autofiller.models import FieldSemantics, FormField
from pdf_autofiller.pipeline import enrich_fields
from pdf_autofiller.semantics_cache import cache_stats, clear_semantics_cache
from pdf_autofiller.settings import Settings, set_settings


@pytest.fixture(autouse=True)
def _settings():
    set_settings(Settings(auth_enabled=False, provider_api_key="test-key", provider_max_retries=1))
    clear_semantics_cache()
    yield
    clear_semantics_cache()
    set_settings(None)


def _fields(count: int) -> list[FormField]:
    return [
        FormField(name=f"txtField{i}", field_type="text", required=False, page_number=1)
        for i in range(count)
    ]


class FakeCompletions:
    def __init__(self, responder):
        self.responder = responder
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        content = self.responder(kwargs, len(self.calls))

        class Message:
            def __init__(self, c):
                self.content = c

        class Choice:
            def __init__(self, c):
                self.message = Message(c)

        class Response:
            def __init__(self, c):
                self.choices = [Choice(c)]

        return Response(content)


class FakeProviderClient:
    def __init__(self, responder):
        self.chat = type("Chat", (), {})()
        self.chat.completions = FakeCompletions(responder)


def _install(monkeypatch, responder) -> FakeProviderClient:
    fake = FakeProviderClient(responder)
    monkeypatch.setattr(field_semantics.SemanticClient, "is_available", lambda self: True)
    monkeypatch.setattr(
        field_semantics.SemanticClient, "__init__",
        lambda self, *a, **k: (
            setattr(self, "_client", fake),
            setattr(self, "model", "test-model"),
            setattr(self, "timeout_seconds", 5.0),
            setattr(self, "max_retries", 1),
            setattr(self, "api_key", "test-key"),
            None,
        )[-1],
    )
    return fake


def _ok_response(fields: list[str]) -> str:
    return json.dumps(
        {
            "fields": [
                {
                    "field_name": name,
                    "semantic_meaning": "first_name",
                    "expected_data_type": "string",
                    "confidence_score": 0.9,
                }
                for name in fields
            ]
        }
    )


def test_one_call_covers_the_whole_form(monkeypatch):
    """A 30-field form must not be 30 round trips."""
    fields = _fields(30)
    fake = _install(monkeypatch, lambda kw, n: _ok_response([f.name for f in fields]))

    result = field_semantics.infer_fields_semantics(fields, {})

    assert len(result) == 30
    assert len(fake.chat.completions.calls) == 1


def test_large_forms_are_chunked(monkeypatch):
    """Chunking keeps a huge form inside the provider's context window."""
    set_settings(
        Settings(auth_enabled=False, provider_api_key="k", provider_batch_size=10)
    )
    fields = _fields(25)

    def responder(kwargs, call_number):
        payload = json.loads(kwargs["messages"][1]["content"].split("Fields:\n", 1)[1].split("\n\nReturn")[0])
        return _ok_response([entry["field_name"] for entry in payload])

    fake = _install(monkeypatch, responder)
    result = field_semantics.infer_fields_semantics(fields, {})

    assert len(fake.chat.completions.calls) == 3  # 10 + 10 + 5
    assert len(result) == 25


def test_strict_schema_is_requested(monkeypatch):
    fields = _fields(2)
    fake = _install(monkeypatch, lambda kw, n: _ok_response([f.name for f in fields]))
    field_semantics.infer_fields_semantics(fields, {})

    fmt = fake.chat.completions.calls[0]["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["strict"] is True
    assert "fields" in fmt["json_schema"]["schema"]["properties"]


def test_schema_rejection_falls_back_to_json_mode(monkeypatch):
    """Not every provider or model accepts strict schemas; that must not be fatal."""
    fields = _fields(2)

    def responder(kwargs, call_number):
        if kwargs["response_format"]["type"] == "json_schema":
            raise ValueError("response_format json_schema is not supported")
        return _ok_response([f.name for f in fields])

    fake = _install(monkeypatch, responder)
    result = field_semantics.infer_fields_semantics(fields, {})

    assert len(result) == 2
    assert fake.chat.completions.calls[0]["response_format"]["type"] == "json_schema"
    assert fake.chat.completions.calls[1]["response_format"]["type"] == "json_object"


def test_transient_failure_is_retried(monkeypatch):
    fields = _fields(1)

    def responder(kwargs, call_number):
        if call_number == 1:
            raise ConnectionError("provider hiccup")
        return _ok_response([f.name for f in fields])

    fake = _install(monkeypatch, responder)
    monkeypatch.setattr(field_semantics.time, "sleep", lambda _s: None)

    result = field_semantics.infer_fields_semantics(fields, {})
    assert len(result) == 1
    assert len(fake.chat.completions.calls) == 2


def test_hallucinated_field_names_are_discarded(monkeypatch):
    """A field name the form does not contain must never become a mapping decision."""
    fields = _fields(2)
    _install(
        monkeypatch,
        lambda kw, n: json.dumps(
            {
                "fields": [
                    {
                        "field_name": "txtField0",
                        "semantic_meaning": "first_name",
                        "expected_data_type": "string",
                        "confidence_score": 0.9,
                    },
                    {
                        "field_name": "txtNotInThisForm",
                        "semantic_meaning": "invented",
                        "expected_data_type": "string",
                        "confidence_score": 0.99,
                    },
                ]
            }
        ),
    )

    result = field_semantics.infer_fields_semantics(fields, {})
    assert set(result) == {"txtField0"}


def test_malformed_entries_are_skipped_not_fatal(monkeypatch):
    fields = _fields(3)
    _install(
        monkeypatch,
        lambda kw, n: json.dumps(
            {
                "fields": [
                    {"field_name": "txtField0", "semantic_meaning": "a",
                     "expected_data_type": "string", "confidence_score": 0.9},
                    {"field_name": "txtField1", "expected_data_type": "string"},
                    {"field_name": "txtField2", "semantic_meaning": "c",
                     "expected_data_type": "not-a-type", "confidence_score": 0.5},
                ]
            }
        ),
    )
    result = field_semantics.infer_fields_semantics(fields, {})
    assert set(result) == {"txtField0"}


def test_provider_outage_degrades_to_fallback(monkeypatch):
    """An unreachable provider must degrade the result, not fail the request."""
    fields = _fields(2)
    _install(monkeypatch, lambda kw, n: (_ for _ in ()).throw(ConnectionError("down")))
    monkeypatch.setattr(field_semantics.time, "sleep", lambda _s: None)

    enriched = enrich_fields(fields, use_semantic_inference=True, page_context={})
    assert len(enriched) == 2
    # Deterministic fallback derives meaning from the field name.
    assert all(e.semantics.confidence_score == 0.5 for e in enriched)


def test_prompt_never_contains_field_values(monkeypatch):
    """Field values may be PII and must not leave the service."""
    fields = [
        FormField(
            name="txtSSN",
            field_type="text",
            value="123-45-6789",
            required=True,
            page_number=1,
        )
    ]
    fake = _install(monkeypatch, lambda kw, n: _ok_response(["txtSSN"]))
    field_semantics.infer_fields_semantics(fields, {1: "Social Security Number"})

    prompt = json.dumps(fake.chat.completions.calls[0]["messages"])
    assert "123-45-6789" not in prompt
    assert "has_value" in prompt  # presence only
    assert "Social Security Number" in prompt  # page context is fine to send


def test_semantics_are_cached_by_form_fingerprint(monkeypatch):
    """The same form filled twice must infer once."""
    fields = _fields(3)
    fake = _install(monkeypatch, lambda kw, n: _ok_response([f.name for f in fields]))

    first = enrich_fields(
        fields, use_semantic_inference=True, page_context={}, fingerprint="fp-1"
    )
    second = enrich_fields(
        fields, use_semantic_inference=True, page_context={}, fingerprint="fp-1"
    )

    assert len(fake.chat.completions.calls) == 1
    assert [e.semantics.semantic_meaning for e in first] == [
        e.semantics.semantic_meaning for e in second
    ]
    assert cache_stats()["entries"] == 1

    # A different form must not read the first form's answer.
    enrich_fields(fields, use_semantic_inference=True, page_context={}, fingerprint="fp-2")
    assert len(fake.chat.completions.calls) == 2


def test_cache_evicts_least_recently_used():
    from pdf_autofiller.semantics_cache import get_cached_semantics, store_cached_semantics

    set_settings(Settings(auth_enabled=False, semantics_cache_size=2))
    payload = {"f": FieldSemantics(
        semantic_meaning="x", expected_data_type="string", confidence_score=0.5
    )}
    store_cached_semantics("a", payload)
    store_cached_semantics("b", payload)
    get_cached_semantics("a")          # 'a' becomes most recent
    store_cached_semantics("c", payload)

    assert get_cached_semantics("b") is None
    assert get_cached_semantics("a") is not None
    assert get_cached_semantics("c") is not None


def test_cache_disabled_when_size_is_zero():
    from pdf_autofiller.semantics_cache import get_cached_semantics, store_cached_semantics

    set_settings(Settings(auth_enabled=False, semantics_cache_size=0))
    store_cached_semantics("a", {})
    assert get_cached_semantics("a") is None


def test_inference_skipped_entirely_when_disabled(monkeypatch):
    fake = _install(monkeypatch, lambda kw, n: _ok_response([]))
    enrich_fields(_fields(5), use_semantic_inference=False, page_context={})
    assert fake.chat.completions.calls == []
