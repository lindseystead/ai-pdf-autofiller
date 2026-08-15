"""Tests for the shared extract → enrich → map → write pipeline."""

import pytest

from pdf_autofiller import pipeline as fill_pipeline
from pdf_autofiller.models import FieldSemantics, FormField, TextRegion
from pdf_autofiller.provider_config import ProviderUsage


def _field(name: str, page: int = 1) -> FormField:
    return FormField(name=name, field_type="text", required=False, page_number=page)


def test_page_context_by_number_groups_text_by_page():
    contexts = fill_pipeline.page_context_by_number(
        [
            TextRegion(text="First", page_number=1),
            TextRegion(text="Second", page_number=1),
            TextRegion(text="Third", page_number=2),
        ]
    )

    assert contexts == {1: "First\nSecond", 2: "Third"}


def test_fallback_semantics_strips_common_field_prefixes():
    enriched = fill_pipeline.fallback_semantics(_field("txtFirstName"))
    assert enriched.semantics.semantic_meaning == "firstname"
    assert enriched.semantics.expected_data_type == "string"


def test_fallback_semantics_handles_unnameable_field():
    enriched = fill_pipeline.fallback_semantics(_field("txt"))
    assert enriched.semantics.semantic_meaning == "unknown_field"


def test_enrich_fields_makes_one_batched_call_for_many_fields(monkeypatch):
    """The semantics stage must not scale provider calls with field count."""
    calls: list[int] = []

    def fake_infer(items, api_key=None, usage=None):
        del api_key
        calls.append(len(items))
        if usage is not None:
            usage.record_call(prompt_tokens=10, completion_tokens=5)
        return {
            field.name: FieldSemantics(
                semantic_meaning="first_name",
                expected_data_type="string",
                confidence_score=0.9,
            )
            for field, _context in items
        }

    monkeypatch.setattr(fill_pipeline, "infer_fields_semantics", fake_infer)

    usage = ProviderUsage()
    fields = [_field(f"field_{index}") for index in range(25)]
    enriched = fill_pipeline.enrich_fields(
        fields, use_semantic_inference=True, page_context={1: "ctx"}, usage=usage
    )

    assert len(enriched) == 25
    assert calls == [25], "expected a single batched request covering every field"
    assert usage.calls == 1
    assert usage.fields_inferred == 25


def test_enrich_fields_passes_page_context_to_provider(monkeypatch):
    observed: dict[str, object] = {}

    def fake_infer(items, api_key=None, usage=None):
        del api_key, usage
        observed["contexts"] = [context for _field, context in items]
        return {}

    monkeypatch.setattr(fill_pipeline, "infer_fields_semantics", fake_infer)

    fill_pipeline.enrich_fields(
        [_field("txtFirstName")],
        use_semantic_inference=True,
        page_context={1: "Applicant First Name"},
    )

    assert observed["contexts"] == ["Applicant First Name"]


def test_enrich_fields_records_and_logs_provider_failure(monkeypatch, caplog):
    """A degraded model path must be recorded, not swallowed."""
    import logging

    def failing_infer(items, api_key=None, usage=None):
        del items, api_key, usage
        raise RuntimeError("provider down")

    monkeypatch.setattr(fill_pipeline, "infer_fields_semantics", failing_infer)

    usage = ProviderUsage()
    with caplog.at_level(logging.WARNING, logger="pdf_autofiller.pipeline"):
        enriched = fill_pipeline.enrich_fields(
            [_field("txtFirstName")], use_semantic_inference=True, usage=usage
        )

    assert len(enriched) == 1
    # Deterministic fallback still produced a usable result...
    assert enriched[0].semantics.semantic_meaning == "firstname"
    # ...but the degradation is visible.
    assert usage.failures == 1
    assert "semantic_inference_failed" in usage.degraded_reasons
    assert "falling back to deterministic" in caplog.text


def test_enrich_fields_flags_partial_inference(monkeypatch):
    def partial_infer(items, api_key=None, usage=None):
        del api_key, usage
        first_field, _context = items[0]
        return {
            first_field.name: FieldSemantics(
                semantic_meaning="first_name",
                expected_data_type="string",
                confidence_score=0.9,
            )
        }

    monkeypatch.setattr(fill_pipeline, "infer_fields_semantics", partial_infer)

    usage = ProviderUsage()
    fill_pipeline.enrich_fields(
        [_field("txtA"), _field("txtB")], use_semantic_inference=True, usage=usage
    )

    assert usage.fields_inferred == 1
    assert "semantic_inference_partial" in usage.degraded_reasons


def test_enrich_fields_without_inference_makes_no_provider_calls(monkeypatch):
    def unexpected(*_args, **_kwargs):
        raise AssertionError("provider must not be contacted on the default path")

    monkeypatch.setattr(fill_pipeline, "infer_fields_semantics", unexpected)

    enriched = fill_pipeline.enrich_fields([_field("txtFirstName")])
    assert enriched[0].semantics.semantic_meaning == "firstname"


def test_enrich_fields_handles_empty_field_list():
    assert fill_pipeline.enrich_fields([], use_semantic_inference=True) == []


@pytest.mark.parametrize(
    ("requested", "applied", "expected_applied"),
    [(False, 0, False), (True, 0, False), (True, 3, True)],
)
def test_build_telemetry_reflects_actual_activity(requested, applied, expected_applied):
    usage = ProviderUsage()
    usage.fields_inferred = applied
    telemetry = fill_pipeline._build_telemetry(
        usage,
        use_semantic_inference=requested,
        allow_fallback_mapping=False,
        fallback_mapping_applied=False,
    )

    assert telemetry.semantic_inference_requested is requested
    assert telemetry.semantic_inference_applied is expected_applied
