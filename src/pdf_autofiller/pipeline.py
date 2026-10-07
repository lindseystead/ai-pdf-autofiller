"""
End-to-end PDF fill pipeline shared by the API, SDK, and integration tests.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .aliases import AliasRegistry
from .field_semantics import SemanticClient
from .field_utils import field_leaf_name, is_opaque_field_name, opaque_mapping_hints
from .mapping import (
    canonicalize_semantic,
    expected_type_for_semantic,
    map_user_data_to_fields,
    normalize_key,
)
from .models import (
    EnrichedFormField,
    FieldSemantics,
    FillOutcome,
    FillReport,
    FormField,
    InspectResult,
    MappingResult,
    PreviewResult,
    TextRegion,
)
from .pdf_reader import read_pdf
from .pdf_writer import fill_pdf

logger = logging.getLogger(__name__)


def fallback_semantics(
    field: FormField,
    registry: AliasRegistry | None = None,
) -> EnrichedFormField:
    """Build deterministic semantics from a field name when inference is disabled."""
    # Hierarchical exports (``applicant.firstName``, ``form1[0].LastName[0]``)
    # carry their meaning in the leaf segment.
    normalized = normalize_key(field_leaf_name(field.name))
    for prefix in ("txt_", "txt", "fld_", "fld", "chk_", "chk"):
        if normalized.startswith(prefix) and len(normalized) > len(prefix):
            normalized = normalized[len(prefix) :]
            break
    # Prefer the canonical alias-pack key (first_name) over a stripped synonym
    # (firstname) so alias clusters and recipes stay consistent.
    semantic = canonicalize_semantic(normalized, registry=registry) if normalized else "unknown_field"
    expected_type = expected_type_for_semantic(semantic, field_type=field.field_type)
    # Opaque widget names rarely match JSON keys via normalize alone — keep
    # confidence low so callers prefer exact keys, aliases, or semantic inference.
    confidence = 0.35 if is_opaque_field_name(field.name) else 0.5

    return EnrichedFormField(
        field=field,
        semantics=FieldSemantics(
            semantic_meaning=semantic,
            expected_data_type=expected_type,
            confidence_score=confidence,
        ),
    )


def page_context_by_number(text_regions: list[TextRegion]) -> dict[int, str]:
    """Group extracted page text for optional semantic inference."""
    grouped_regions: dict[int, list[str]] = {}
    for region in text_regions:
        grouped_regions.setdefault(region.page_number, []).append(region.text)
    return {page_number: "\n".join(chunks) for page_number, chunks in grouped_regions.items()}


def semantic_provider_status(api_key: str | None = None) -> str:
    """
    Report semantic-provider readiness for health checks.

    Returns ``available``, ``unconfigured`` (no API key) or ``sdk_missing`` (a key
    is set but no client could be built: the openai package is missing or client
    setup failed). This only says whether a client exists, not that calls will succeed.
    """
    client = SemanticClient(api_key=api_key)
    if client.is_available():
        return "available"
    if not client.api_key:
        return "unconfigured"
    return "sdk_missing"


def enrich_fields(
    fields: list[FormField],
    *,
    use_semantic_inference: bool = False,
    page_context: dict[int, str] | None = None,
    registry: AliasRegistry | None = None,
) -> list[EnrichedFormField]:
    """Enrich extracted fields with semantic inference or deterministic fallback.

    When inference is requested, fields are sent in a **single** provider call.
    On partial or total failure it logs a warning and falls back to deterministic
    name-based semantics for the affected fields.
    """
    inferred: dict[str, FieldSemantics] = {}
    batch_failed = False
    if use_semantic_inference and fields:
        try:
            client = SemanticClient()
            inferred = client.infer_semantics_batch(fields, page_context=page_context)
        except (RuntimeError, ValueError) as exc:
            batch_failed = True
            logger.warning(
                "Batch semantic inference failed for %d fields; using deterministic fallback: %s",
                len(fields),
                exc,
            )

    enriched_fields: list[EnrichedFormField] = []
    for field in fields:
        semantics = inferred.get(field.name)
        if semantics is not None:
            enriched_fields.append(EnrichedFormField(field=field, semantics=semantics, ai_inferred=True))
        else:
            if use_semantic_inference and not batch_failed:
                logger.warning(
                    "Semantic inference missing for field=%s; using deterministic fallback",
                    field.name,
                )
            enriched_fields.append(fallback_semantics(field, registry=registry))

    return enriched_fields


def inspect(pdf: str | Path, *, max_pages: int | None = None) -> InspectResult:
    """List AcroForm fields locally (no HTTP server)."""
    structure = read_pdf(Path(pdf), max_pages=max_pages)
    fields = list(structure.form_fields)
    opaque_names = [field.name for field in fields if is_opaque_field_name(field.name)]
    return InspectResult(
        pages=structure.metadata.num_pages,
        field_count=len(fields),
        fields=fields,
        opaque_field_count=len(opaque_names),
        opaque_fields=opaque_names[:50],
        mapping_hints=opaque_mapping_hints([field.name for field in fields]),
    )


def require_consistent_options(*, strict: bool, allow_fallback_mapping: bool) -> None:
    """Strict mode disables the AI key fallback, so asking for both is a caller error."""
    if strict and allow_fallback_mapping:
        raise ValueError(
            "allow_fallback_mapping=True needs strict=False (strict mode disables the AI key fallback)"
        )


def run_preview_pipeline(
    input_pdf_path: Path,
    user_data: dict[str, Any],
    *,
    strict: bool = True,
    allow_fallback_mapping: bool = False,
    use_semantic_inference: bool = False,
    max_pages: int | None = None,
    registry: AliasRegistry | None = None,
) -> tuple[MappingResult, int, int]:
    """Run extract → enrich → map without writing a PDF.

    Returns ``(mapping_result, field_count, page_count)``.
    """
    require_consistent_options(strict=strict, allow_fallback_mapping=allow_fallback_mapping)
    structure = read_pdf(input_pdf_path, max_pages=max_pages)
    enriched_fields = enrich_fields(
        structure.form_fields,
        use_semantic_inference=use_semantic_inference,
        page_context=page_context_by_number(structure.text_regions),
        registry=registry,
    )
    mapping_result = map_user_data_to_fields(
        enriched_fields,
        user_data,
        strict=strict,
        allow_fallback_mapping=allow_fallback_mapping,
        use_semantic_inference=use_semantic_inference,
        registry=registry,
    )
    return mapping_result, len(enriched_fields), structure.metadata.num_pages


def preview(
    pdf: str | Path,
    user_data: dict[str, Any],
    *,
    strict: bool = True,
    allow_fallback_mapping: bool = False,
    use_semantic_inference: bool = False,
    max_pages: int | None = None,
    registry: AliasRegistry | None = None,
) -> PreviewResult:
    """Preview mapping decisions locally without writing a PDF."""
    mapping_result, field_count, page_count = run_preview_pipeline(
        Path(pdf),
        user_data,
        strict=strict,
        allow_fallback_mapping=allow_fallback_mapping,
        use_semantic_inference=use_semantic_inference,
        max_pages=max_pages,
        registry=registry,
    )
    return PreviewResult(pages=page_count, field_count=field_count, mapping=mapping_result)


def run_fill_pipeline(
    input_pdf_path: Path,
    output_pdf_path: Path,
    user_data: dict[str, Any],
    *,
    strict: bool = True,
    allow_fallback_mapping: bool = False,
    use_semantic_inference: bool = False,
    max_pages: int | None = None,
    flatten: bool = False,
    need_appearances: bool = True,
    allow_partial: bool = False,
    registry: AliasRegistry | None = None,
) -> tuple[FillReport, MappingResult, int, int]:
    """Run extract → enrich → map → write.

    Returns ``(fill_report, mapping_result, field_count, page_count)``.
    """
    require_consistent_options(strict=strict, allow_fallback_mapping=allow_fallback_mapping)
    structure = read_pdf(input_pdf_path, max_pages=max_pages)
    enriched_fields = enrich_fields(
        structure.form_fields,
        use_semantic_inference=use_semantic_inference,
        page_context=page_context_by_number(structure.text_regions),
        registry=registry,
    )
    mapping_result = map_user_data_to_fields(
        enriched_fields,
        user_data,
        strict=strict,
        allow_fallback_mapping=allow_fallback_mapping,
        use_semantic_inference=use_semantic_inference,
        registry=registry,
    )
    fill_report = fill_pdf(
        input_pdf_path,
        output_pdf_path,
        mapping_result,
        flatten=flatten,
        need_appearances=need_appearances,
        allow_partial=allow_partial,
    )
    return (
        fill_report,
        mapping_result,
        len(enriched_fields),
        structure.metadata.num_pages,
    )


def fill(
    pdf: str | Path,
    user_data: dict[str, Any],
    output: str | Path,
    *,
    strict: bool = True,
    allow_fallback_mapping: bool = False,
    use_semantic_inference: bool = False,
    max_pages: int | None = None,
    flatten: bool = False,
    need_appearances: bool = True,
    allow_partial: bool = False,
    registry: AliasRegistry | None = None,
) -> FillReport:
    """
    Fill a PDF locally (no HTTP server required).

    Example::

        from pdf_autofiller import fill
        fill("form.pdf", {"firstname": "Jane"}, "filled.pdf")
    """
    report, _mapping, _count, _pages = run_fill_pipeline(
        Path(pdf),
        Path(output),
        user_data,
        strict=strict,
        allow_fallback_mapping=allow_fallback_mapping,
        use_semantic_inference=use_semantic_inference,
        max_pages=max_pages,
        flatten=flatten,
        need_appearances=need_appearances,
        allow_partial=allow_partial,
        registry=registry,
    )
    return report


def fill_detailed(
    pdf: str | Path,
    user_data: dict[str, Any],
    output: str | Path,
    *,
    strict: bool = True,
    allow_fallback_mapping: bool = False,
    use_semantic_inference: bool = False,
    max_pages: int | None = None,
    flatten: bool = False,
    need_appearances: bool = True,
    allow_partial: bool = False,
    registry: AliasRegistry | None = None,
) -> FillOutcome:
    """Fill a PDF and return write report + mapping decisions together."""
    report, mapping, field_count, pages = run_fill_pipeline(
        Path(pdf),
        Path(output),
        user_data,
        strict=strict,
        allow_fallback_mapping=allow_fallback_mapping,
        use_semantic_inference=use_semantic_inference,
        max_pages=max_pages,
        flatten=flatten,
        need_appearances=need_appearances,
        allow_partial=allow_partial,
        registry=registry,
    )
    return FillOutcome(
        report=report,
        mapping=mapping,
        field_count=field_count,
        pages=pages,
    )
