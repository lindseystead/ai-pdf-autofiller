"""
End-to-end PDF fill pipeline shared by the API, SDK, and integration tests.
"""

from pathlib import Path
from typing import Any

from .field_semantics import infer_field_semantics
from .mapping import map_user_data_to_fields, normalize_key
from .models import EnrichedFormField, FieldSemantics, FillReport, FormField, MappingResult, TextRegion
from .pdf_reader import read_pdf
from .provider_cache import (
    ProviderCacheMetrics,
    compute_form_hash,
    get_provider_cache,
    semantic_cache_key,
)
from .pdf_writer import fill_pdf


def fallback_semantics(field: FormField) -> EnrichedFormField:
    """Build deterministic semantics from a field name when inference is disabled."""
    normalized = normalize_key(field.name)
    normalized = normalized.removeprefix("txt_")
    normalized = normalized.removeprefix("txt")
    semantic = normalized if normalized else "unknown_field"

    return EnrichedFormField(
        field=field,
        semantics=FieldSemantics(
            semantic_meaning=semantic,
            expected_data_type="string",
            confidence_score=0.5,
        ),
    )


def page_context_by_number(text_regions: list[TextRegion]) -> dict[int, str]:
    """Group extracted page text for optional semantic inference."""
    grouped_regions: dict[int, list[str]] = {}
    for region in text_regions:
        grouped_regions.setdefault(region.page_number, []).append(region.text)
    return {page_number: "\n".join(chunks) for page_number, chunks in grouped_regions.items()}


def enrich_fields(
    fields: list[FormField],
    *,
    use_semantic_inference: bool = False,
    page_context: dict[int, str] | None = None,
    form_hash: str | None = None,
    cache_metrics: ProviderCacheMetrics | None = None,
) -> list[EnrichedFormField]:
    """Enrich extracted fields with semantic inference or deterministic fallback."""
    enriched_fields: list[EnrichedFormField] = []

    for field in fields:
        context_text = page_context.get(field.page_number) if page_context else None
        if use_semantic_inference:
            cache_key = None
            if form_hash:
                cache_key = semantic_cache_key(
                    form_hash=form_hash, field=field, context_text=context_text
                )
                cached_semantics = get_provider_cache().get(cache_key)
                if isinstance(cached_semantics, dict):
                    try:
                        if cache_metrics:
                            cache_metrics.semantic_hits += 1
                        enriched_fields.append(
                            EnrichedFormField(field=field, semantics=FieldSemantics(**cached_semantics))
                        )
                        continue
                    except Exception:
                        pass
                if cache_metrics:
                    cache_metrics.semantic_misses += 1
            try:
                inferred_field = infer_field_semantics(field, context_text=context_text)
                if cache_key:
                    get_provider_cache().set(cache_key, inferred_field.semantics.model_dump())
                enriched_fields.append(inferred_field)
                continue
            except (RuntimeError, ValueError):
                pass
        enriched_fields.append(fallback_semantics(field))

    return enriched_fields


def run_fill_pipeline(
    input_pdf_path: Path,
    output_pdf_path: Path,
    user_data: dict[str, Any],
    *,
    strict: bool = True,
    allow_fallback_mapping: bool = False,
    use_semantic_inference: bool = False,
    max_pages: int | None = None,
) -> tuple[FillReport, MappingResult, int, ProviderCacheMetrics]:
    """Run extract → enrich → map → write and return the fill report."""
    form_hash = compute_form_hash(input_pdf_path)
    cache_metrics = ProviderCacheMetrics()
    structure = read_pdf(input_pdf_path, max_pages=max_pages)
    enriched_fields = enrich_fields(
        structure.form_fields,
        use_semantic_inference=use_semantic_inference,
        page_context=page_context_by_number(structure.text_regions),
        form_hash=form_hash,
        cache_metrics=cache_metrics,
    )
    mapping_result = map_user_data_to_fields(
        enriched_fields,
        user_data,
        strict=strict,
        allow_fallback_mapping=allow_fallback_mapping,
        form_hash=form_hash,
        cache_metrics=cache_metrics,
    )
    fill_report = fill_pdf(input_pdf_path, output_pdf_path, mapping_result)
    return fill_report, mapping_result, len(enriched_fields), cache_metrics
