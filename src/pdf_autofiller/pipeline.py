"""
End-to-end PDF fill pipeline shared by the API, SDK, and integration tests.

The default path is fully deterministic. When semantic inference is enabled the
stage makes one batched provider call per group of fields rather than one call
per field, and any degradation is recorded in :class:`PipelineTelemetry` so the
caller can tell a model-assisted run from one that quietly fell back.
"""

import logging
from pathlib import Path
from typing import Any

from .field_semantics import infer_fields_semantics
from .mapping import map_user_data_to_fields, normalize_key
from .models import (
    EnrichedFormField,
    FieldSemantics,
    FormField,
    PipelineResult,
    PipelineTelemetry,
    TextRegion,
)
from .pdf_reader import read_pdf
from .pdf_writer import fill_pdf
from .provider_config import ProviderUsage

logger = logging.getLogger(__name__)

FALLBACK_CONFIDENCE = 0.5


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
            confidence_score=FALLBACK_CONFIDENCE,
        ),
    )


def page_context_by_number(text_regions: list[TextRegion]) -> dict[int, str]:
    """Group extracted page text for optional semantic inference."""
    grouped_regions: dict[int, list[str]] = {}
    for region in text_regions:
        grouped_regions.setdefault(region.page_number, []).append(region.text)
    return {
        page_number: "\n".join(chunks) for page_number, chunks in grouped_regions.items()
    }


def enrich_fields(
    fields: list[FormField],
    *,
    use_semantic_inference: bool = False,
    page_context: dict[int, str] | None = None,
    api_key: str | None = None,
    usage: ProviderUsage | None = None,
) -> list[EnrichedFormField]:
    """
    Enrich extracted fields with semantic inference or deterministic fallback.

    Inference is requested for the whole form in one batched call. Fields the
    provider does not resolve fall back to name-derived semantics individually,
    so a partial response still produces a complete result.
    """
    usage = usage if usage is not None else ProviderUsage()

    if not fields:
        return []

    inferred: dict[str, FieldSemantics] = {}
    if use_semantic_inference:
        items = [
            (field, page_context.get(field.page_number) if page_context else None)
            for field in fields
        ]
        try:
            inferred = infer_fields_semantics(items, api_key=api_key, usage=usage)
        except (RuntimeError, ValueError) as exc:
            # Degrading to deterministic semantics is correct, but it must be
            # visible: a silent fallback is indistinguishable from success.
            logger.warning(
                "Semantic inference unavailable; falling back to deterministic "
                "field-name semantics: %s",
                exc,
            )
            usage.record_failure("semantic_inference_failed")

        if not inferred:
            usage.note_degraded("semantic_inference_not_applied")

    enriched_fields: list[EnrichedFormField] = []
    for field in fields:
        semantics = inferred.get(field.name)
        if semantics is not None:
            enriched_fields.append(EnrichedFormField(field=field, semantics=semantics))
        else:
            enriched_fields.append(fallback_semantics(field))

    usage.fields_inferred = len(inferred)
    if use_semantic_inference and 0 < len(inferred) < len(fields):
        usage.note_degraded("semantic_inference_partial")

    return enriched_fields


def _build_telemetry(
    usage: ProviderUsage,
    *,
    use_semantic_inference: bool,
    allow_fallback_mapping: bool,
    fallback_mapping_applied: bool,
) -> PipelineTelemetry:
    """Freeze a mutable usage accumulator into the reported telemetry contract."""
    return PipelineTelemetry(
        semantic_inference_requested=use_semantic_inference,
        semantic_inference_applied=usage.fields_inferred > 0,
        fallback_mapping_requested=allow_fallback_mapping,
        fallback_mapping_applied=fallback_mapping_applied,
        fields_inferred=usage.fields_inferred,
        provider_calls=usage.calls,
        provider_retries=usage.retries,
        provider_failures=usage.failures,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        degraded_reasons=list(usage.degraded_reasons),
    )


def run_fill_pipeline(
    input_pdf_path: Path,
    output_pdf_path: Path,
    user_data: dict[str, Any],
    *,
    strict: bool = True,
    allow_fallback_mapping: bool = False,
    use_semantic_inference: bool = False,
    max_pages: int | None = None,
    api_key: str | None = None,
) -> PipelineResult:
    """Run extract → enrich → map → write and return the outcome plus telemetry."""
    usage = ProviderUsage()

    structure = read_pdf(input_pdf_path, max_pages=max_pages)
    enriched_fields = enrich_fields(
        structure.form_fields,
        use_semantic_inference=use_semantic_inference,
        page_context=page_context_by_number(structure.text_regions),
        api_key=api_key,
        usage=usage,
    )
    mapping_result = map_user_data_to_fields(
        enriched_fields,
        user_data,
        strict=strict,
        allow_fallback_mapping=allow_fallback_mapping,
        api_key=api_key,
        usage=usage,
    )
    fallback_mapping_applied = any(
        decision.confidence_source == "model" for decision in mapping_result.decisions
    )
    fill_report = fill_pdf(input_pdf_path, output_pdf_path, mapping_result)

    return PipelineResult(
        fill_report=fill_report,
        mapping_result=mapping_result,
        fields_total=len(enriched_fields),
        telemetry=_build_telemetry(
            usage,
            use_semantic_inference=use_semantic_inference,
            allow_fallback_mapping=allow_fallback_mapping,
            fallback_mapping_applied=fallback_mapping_applied,
        ),
    )
