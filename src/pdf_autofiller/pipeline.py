"""
End-to-end PDF fill pipeline shared by the API, SDK, and integration tests.
"""

from pathlib import Path
from typing import Any

from .field_semantics import infer_field_semantics
from .mapping import canonicalize_semantic, map_user_data_to_fields, normalize_key
from .models import (
    EnrichedFormField,
    FieldSemantics,
    FillReport,
    FormField,
    MappingResult,
    TextRegion,
)
from .pdf_reader import read_pdf
from .pdf_writer import fill_pdf


def fallback_semantics(field: FormField) -> EnrichedFormField:
    """Build deterministic semantics from a field name when inference is disabled."""
    normalized = normalize_key(field.name)
    for prefix in ("txt_", "txt", "fld_", "fld"):
        if normalized.startswith(prefix) and len(normalized) > len(prefix):
            normalized = normalized[len(prefix) :]
            break
    # Prefer the canonical alias-pack key (first_name) over a stripped synonym
    # (firstname) so alias clusters and recipes stay consistent.
    semantic = canonicalize_semantic(normalized) if normalized else "unknown_field"

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
) -> list[EnrichedFormField]:
    """Enrich extracted fields with semantic inference or deterministic fallback."""
    enriched_fields: list[EnrichedFormField] = []

    for field in fields:
        context_text = page_context.get(field.page_number) if page_context else None
        if use_semantic_inference:
            try:
                enriched_fields.append(infer_field_semantics(field, context_text=context_text))
                continue
            except (RuntimeError, ValueError):
                pass
        enriched_fields.append(fallback_semantics(field))

    return enriched_fields


def run_preview_pipeline(
    input_pdf_path: Path,
    user_data: dict[str, Any],
    *,
    strict: bool = True,
    allow_fallback_mapping: bool = False,
    use_semantic_inference: bool = False,
    max_pages: int | None = None,
) -> tuple[MappingResult, int, int]:
    """Run extract → enrich → map without writing a PDF.

    Returns ``(mapping_result, field_count, page_count)``.
    """
    structure = read_pdf(input_pdf_path, max_pages=max_pages)
    enriched_fields = enrich_fields(
        structure.form_fields,
        use_semantic_inference=use_semantic_inference,
        page_context=page_context_by_number(structure.text_regions),
    )
    mapping_result = map_user_data_to_fields(
        enriched_fields,
        user_data,
        strict=strict,
        allow_fallback_mapping=allow_fallback_mapping,
    )
    return mapping_result, len(enriched_fields), structure.metadata.num_pages


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
) -> tuple[FillReport, MappingResult, int]:
    """Run extract → enrich → map → write and return the fill report."""
    structure = read_pdf(input_pdf_path, max_pages=max_pages)
    enriched_fields = enrich_fields(
        structure.form_fields,
        use_semantic_inference=use_semantic_inference,
        page_context=page_context_by_number(structure.text_regions),
    )
    mapping_result = map_user_data_to_fields(
        enriched_fields,
        user_data,
        strict=strict,
        allow_fallback_mapping=allow_fallback_mapping,
    )
    fill_report = fill_pdf(
        input_pdf_path, output_pdf_path, mapping_result, flatten=flatten
    )
    return fill_report, mapping_result, len(enriched_fields)


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
) -> FillReport:
    """
    Fill a PDF locally (no HTTP server required).

    Example::

        from pdf_autofiller import fill
        fill("form.pdf", {"firstname": "Jane"}, "filled.pdf")
    """
    report, _mapping, _count = run_fill_pipeline(
        Path(pdf),
        Path(output),
        user_data,
        strict=strict,
        allow_fallback_mapping=allow_fallback_mapping,
        use_semantic_inference=use_semantic_inference,
        max_pages=max_pages,
        flatten=flatten,
    )
    return report
