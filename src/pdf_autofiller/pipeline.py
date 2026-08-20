"""
End-to-end PDF pipeline shared by the API, CLI, SDK, and integration tests.

Two entry points sit on the same four stages (read -> enrich -> map -> write):

* :func:`run_inspect_pipeline` stops after mapping and reports what a fill
  *would* do. Discovery used to require guessing key names and reading a 422,
  because the pipeline computed this information and then discarded it.
* :func:`run_fill_pipeline` runs all four and produces the document.

Both are module-level and picklable so they can run inside a killable worker
process (see :mod:`pdf_autofiller.execution`).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from .field_semantics import infer_fields_semantics
from .mapping import map_user_data_to_fields, normalize_key
from .models import (
    EnrichedFormField,
    FieldSemantics,
    FillReport,
    FormField,
    InspectReport,
    MappingResult,
    TextRegion,
)
from .pdf_reader import form_fingerprint, read_pdf
from .pdf_writer import fill_pdf
from .semantics_cache import get_cached_semantics, store_cached_semantics

logger = logging.getLogger(__name__)


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
    fingerprint: Optional[str] = None,
) -> list[EnrichedFormField]:
    """
    Enrich extracted fields with semantic inference or deterministic fallback.

    Inference runs as a single batched call for the whole form rather than once
    per field. The old per-field loop meant a 60-field form made 60 serial round
    trips inside one request budget: it timed out, and cost 60x what it should.

    Results are cached against the form's fingerprint, so the same form filled
    twice infers once.
    """
    if not use_semantic_inference:
        return [fallback_semantics(field) for field in fields]

    if fingerprint:
        cached = get_cached_semantics(fingerprint)
        if cached is not None:
            return _apply_cached_semantics(fields, cached)

    inferred = infer_fields_semantics(fields, page_context=page_context or {})

    enriched_fields = [
        EnrichedFormField(field=field, semantics=inferred[field.name])
        if field.name in inferred
        else fallback_semantics(field)
        for field in fields
    ]

    if fingerprint:
        store_cached_semantics(
            fingerprint, {e.field.name: e.semantics for e in enriched_fields}
        )
    return enriched_fields


def _apply_cached_semantics(
    fields: list[FormField], cached: dict[str, FieldSemantics]
) -> list[EnrichedFormField]:
    """Rebuild enriched fields from cached semantics, falling back per field."""
    return [
        EnrichedFormField(field=field, semantics=cached[field.name])
        if field.name in cached
        else fallback_semantics(field)
        for field in fields
    ]


def _prepare(
    input_pdf_path: Path,
    user_data: dict[str, Any],
    *,
    strict: bool,
    allow_fallback_mapping: bool,
    use_semantic_inference: bool,
    max_pages: Optional[int],
    max_text_chars: Optional[int],
    overrides: Optional[dict[str, Any]],
    allow_key_reuse: bool,
) -> tuple[Any, list[EnrichedFormField], MappingResult, str]:
    """Run read -> enrich -> map, the half both entry points share."""
    structure = read_pdf(input_pdf_path, max_pages=max_pages, max_text_chars=max_text_chars)
    fingerprint = form_fingerprint(structure.form_fields)
    enriched_fields = enrich_fields(
        structure.form_fields,
        use_semantic_inference=use_semantic_inference,
        page_context=page_context_by_number(structure.text_regions),
        fingerprint=fingerprint,
    )
    mapping_result = map_user_data_to_fields(
        enriched_fields,
        user_data,
        strict=strict,
        allow_fallback_mapping=allow_fallback_mapping,
        overrides=overrides,
        allow_key_reuse=allow_key_reuse,
    )
    return structure, enriched_fields, mapping_result, fingerprint


def run_inspect_pipeline(
    input_pdf_path: Path,
    user_data: Optional[dict[str, Any]] = None,
    *,
    strict: bool = True,
    allow_fallback_mapping: bool = False,
    use_semantic_inference: bool = False,
    max_pages: int | None = None,
    max_text_chars: int | None = None,
    overrides: Optional[dict[str, Any]] = None,
    allow_key_reuse: bool = True,
) -> InspectReport:
    """Report a form's fields and what a fill would do, without writing anything."""
    structure, enriched_fields, mapping_result, fingerprint = _prepare(
        input_pdf_path,
        user_data or {},
        strict=strict,
        allow_fallback_mapping=allow_fallback_mapping,
        use_semantic_inference=use_semantic_inference,
        max_pages=max_pages,
        max_text_chars=max_text_chars,
        overrides=overrides,
        allow_key_reuse=allow_key_reuse,
    )

    would_write = sorted(
        d.field_name
        for d in mapping_result.decisions
        if not d.requires_review and d.selected_value is not None
    )
    would_skip = sorted(
        {d.field_name for d in mapping_result.decisions if d.requires_review}
        | set(mapping_result.missing_required)
    )

    return InspectReport(
        metadata=structure.metadata,
        fields=enriched_fields,
        mapping=mapping_result if user_data else None,
        fingerprint=fingerprint,
        would_write=would_write,
        would_skip=would_skip,
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
    max_text_chars: int | None = None,
    overrides: Optional[dict[str, Any]] = None,
    allow_key_reuse: bool = True,
    flatten: bool = False,
) -> tuple[FillReport, MappingResult, int]:
    """Run extract -> enrich -> map -> write and return the fill report."""
    _, enriched_fields, mapping_result, _ = _prepare(
        input_pdf_path,
        user_data,
        strict=strict,
        allow_fallback_mapping=allow_fallback_mapping,
        use_semantic_inference=use_semantic_inference,
        max_pages=max_pages,
        max_text_chars=max_text_chars,
        overrides=overrides,
        allow_key_reuse=allow_key_reuse,
    )
    fill_report = fill_pdf(input_pdf_path, output_pdf_path, mapping_result, flatten=flatten)
    return fill_report, mapping_result, len(enriched_fields)


def extract_form_values(
    input_pdf_path: Path,
    *,
    raw: bool = False,
    include_empty: bool = False,
    max_pages: int | None = None,
    max_text_chars: int | None = None,
) -> dict[str, Any]:
    """
    Read the values already present in a filled PDF.

    Completing a form by hand and then re-keying the same data into JSON is the
    kind of work this tool exists to remove. Reading the values back out turns a
    document someone already filled into reusable data.

    Keys are semantic meanings by default (``first_name``), which is the shape
    that feeds ``--data`` or a profile. ``raw=True`` keys by exact PDF field name
    (``txtFirstName``), which is the shape that feeds ``overrides``.

    Empty fields are omitted unless ``include_empty`` is set: a blank field means
    "not answered", and carrying it forward as ``""`` would later overwrite a
    real value with nothing.

    Semantic keys can collide when a form has two fields that mean the same
    thing. The first value wins and the collision is logged, because silently
    keeping the last one would depend on field order.
    """
    structure = read_pdf(
        input_pdf_path, max_pages=max_pages, max_text_chars=max_text_chars
    )

    values: dict[str, Any] = {}
    for field in structure.form_fields:
        if field.value is None or (not include_empty and not str(field.value).strip()):
            continue
        key = field.name if raw else fallback_semantics(field).semantics.semantic_meaning
        if key in values and values[key] != field.value:
            logger.info(
                "Two fields resolve to %r with different values; keeping the first. "
                "Use raw=True to keep both.",
                key,
            )
            continue
        values[key] = field.value

    return values


def data_skeleton(
    input_pdf_path: Path,
    *,
    max_pages: int | None = None,
    max_text_chars: int | None = None,
) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    """
    Build a starter data file carrying the keys this form actually wants.

    ``inspect`` reports what is missing; this produces the file to fill in, so a
    first encounter with a form does not start by guessing key names.

    Returns the skeleton (required keys first, so the important ones are at the
    top of the file) and a per-key annotation map describing which field each key
    feeds and whether it is required.
    """
    structure = read_pdf(
        input_pdf_path, max_pages=max_pages, max_text_chars=max_text_chars
    )
    enriched = [fallback_semantics(field) for field in structure.form_fields]
    # Required first, then original document order within each group.
    ordered = sorted(enriched, key=lambda e: not e.field.required)

    skeleton: dict[str, str] = {}
    annotations: dict[str, dict[str, Any]] = {}
    for item in ordered:
        key = item.semantics.semantic_meaning
        if key in skeleton:
            annotations[key]["fields"].append(item.field.name)
            continue
        skeleton[key] = ""
        annotations[key] = {
            "fields": [item.field.name],
            "required": item.field.required,
            "type": item.field.field_type,
            "options": item.field.options,
        }

    return skeleton, annotations
