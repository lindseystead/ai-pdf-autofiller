"""Tests for pipeline enrichment helpers."""

from pdf_autofiller import pipeline
from pdf_autofiller.models import EnrichedFormField, FieldSemantics, FormField
from pdf_autofiller.provider_cache import ProviderCacheMetrics, reset_provider_cache_for_tests


def test_enrich_fields_uses_semantic_cache_for_same_form_hash(monkeypatch):
    calls = {"count": 0}
    field = FormField(name="txtFirstName", field_type="text", required=True, page_number=1)

    def fake_infer(input_field, context_text=None):
        calls["count"] += 1
        assert context_text == "Applicant First Name"
        return EnrichedFormField(
            field=input_field,
            semantics=FieldSemantics(
                semantic_meaning="first_name",
                expected_data_type="string",
                confidence_score=0.95,
            ),
        )

    reset_provider_cache_for_tests()
    monkeypatch.setattr(pipeline, "infer_field_semantics", fake_infer)
    metrics = ProviderCacheMetrics()

    first = pipeline.enrich_fields(
        [field],
        use_semantic_inference=True,
        page_context={1: "Applicant First Name"},
        form_hash="form-a",
        cache_metrics=metrics,
    )
    second = pipeline.enrich_fields(
        [field],
        use_semantic_inference=True,
        page_context={1: "Applicant First Name"},
        form_hash="form-a",
        cache_metrics=metrics,
    )

    reset_provider_cache_for_tests()
    assert first[0].semantics.semantic_meaning == "first_name"
    assert second[0].semantics.semantic_meaning == "first_name"
    assert calls["count"] == 1
    assert metrics.semantic_hits == 1
    assert metrics.semantic_misses == 1

