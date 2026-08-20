"""
Behaviour that must survive refactoring.

These tests exist to be run before and after restructuring `fill_pdf` and
`map_user_data_to_fields`. They assert observable output rather than internal
structure, so they stay true no matter how the code is arranged — and they fail
loudly if a "pure" refactor moves a single byte of a produced document.

Written before the refactor, deliberately. A safety net added afterwards only
proves the new code agrees with itself.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from pdf_autofiller.mapping import map_user_data_to_fields
from pdf_autofiller.models import (
    EnrichedFormField,
    FieldMappingDecision,
    FieldSemantics,
    FormField,
    MappingResult,
)
from pdf_autofiller.pdf_writer import fill_pdf
from pdf_autofiller.pipeline import run_fill_pipeline

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "sample_form.pdf"
DATA = {
    "firstname": "Jane",
    "lastname": "Doe",
    "dob": "1990-01-01",
    "email": "jane@example.com",
    "phone": "555-0100",
}


def _field(name: str, semantic: str, *, required: bool = False) -> EnrichedFormField:
    return EnrichedFormField(
        field=FormField(name=name, field_type="text", required=required, page_number=1),
        semantics=FieldSemantics(
            semantic_meaning=semantic, expected_data_type="string", confidence_score=0.9
        ),
    )


def _content_fingerprint(pdf_path: Path) -> str:
    """Hash the *content* of a filled PDF, ignoring incidental byte differences.

    Raw file bytes are not stable across runs — object ordering and ids can
    shift — so hashing the file would produce a test that fails for no reason.
    Field names, values, page count, and extracted page text are the things a
    refactor must not change.
    """
    reader = PdfReader(str(pdf_path))
    fields = {name: str(obj.get("/V")) for name, obj in (reader.get_fields() or {}).items()}
    payload = {
        "pages": len(reader.pages),
        "fields": dict(sorted(fields.items())),
        "text": [(page.extract_text() or "").strip() for page in reader.pages],
        "has_acroform": "/AcroForm" in reader.trailer["/Root"],
        "widgets": sum(
            1
            for page in reader.pages
            for annot in (page.get("/Annots") or [])
            if annot.get_object().get("/Subtype") == "/Widget"
        ),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


# --- writer output ---------------------------------------------------------


@pytest.mark.parametrize("flatten", [False, True])
def test_filled_document_content_is_stable(tmp_path, flatten):
    """The exact bytes may move; what the document *says* may not."""
    first = tmp_path / "a.pdf"
    second = tmp_path / "b.pdf"
    run_fill_pipeline(SAMPLE, first, DATA, strict=True, flatten=flatten)
    run_fill_pipeline(SAMPLE, second, DATA, strict=True, flatten=flatten)

    assert _content_fingerprint(first) == _content_fingerprint(second)


def test_fill_report_shape_is_stable(tmp_path):
    report, mapping, total = run_fill_pipeline(SAMPLE, tmp_path / "o.pdf", DATA, strict=True)

    assert total == 5
    assert report.written_fields == [
        "txtDOB",
        "txtEmail",
        "txtFirstName",
        "txtLastName",
        "txtPhone",
    ]
    assert report.skipped_review_fields == []
    assert report.skipped_empty_fields == []
    assert report.skipped_invalid_fields == []
    assert report.flattened is False
    assert mapping.missing_required == []
    assert mapping.unmapped_user_keys == []


def test_writer_skip_classification_is_stable(tmp_path):
    """Each skip reason must keep landing in its own bucket."""
    result = MappingResult(
        decisions=[
            FieldMappingDecision(
                field_name="txtFirstName", semantic_meaning="first_name",
                selected_value="Jane", confidence=0.95, reason="d", requires_review=False,
            ),
            FieldMappingDecision(
                field_name="txtEmail", semantic_meaning="email",
                selected_value="x", confidence=0.4, reason="low", requires_review=True,
            ),
            FieldMappingDecision(
                field_name="txtPhone", semantic_meaning="phone",
                selected_value=None, confidence=0.9, reason="none", requires_review=False,
            ),
            FieldMappingDecision(
                field_name="notAFieldOnThisForm", semantic_meaning="x",
                selected_value="v", confidence=0.9, reason="d", requires_review=False,
            ),
        ],
        missing_required=[],
    )
    with pytest.raises(Exception) as excinfo:
        fill_pdf(SAMPLE, tmp_path / "o.pdf", result)
    # txtLastName and txtDOB are required and were never supplied.
    assert sorted(excinfo.value.missing_fields) == ["txtDOB", "txtLastName"]


def test_unknown_field_names_are_ignored_not_written(tmp_path):
    result = MappingResult(
        decisions=[
            FieldMappingDecision(
                field_name=name, semantic_meaning="s", selected_value="v",
                confidence=0.95, reason="d", requires_review=False,
            )
            for name in ("txtFirstName", "txtLastName", "txtDOB", "ghostField")
        ]
    )
    report = fill_pdf(SAMPLE, tmp_path / "o.pdf", result)
    assert "ghostField" not in report.written_fields


# --- mapping decisions -----------------------------------------------------


def test_mapping_decision_details_are_stable():
    """Confidence, reason wording, and review flags are part of the contract.

    Callers audit fills by reading `reason`, so it is observable behaviour.
    """
    fields = [_field("f_first", "first_name", required=True), _field("f_city", "city")]
    result = map_user_data_to_fields(fields, {"firstname": "Jane", "city": "Boston"}, strict=True)

    by_name = {d.field_name: d for d in result.decisions}
    assert by_name["f_first"].selected_value == "Jane"
    assert by_name["f_first"].confidence == pytest.approx(0.90)
    assert by_name["f_first"].requires_review is False
    assert "Alias match" in by_name["f_first"].reason

    assert by_name["f_city"].selected_value == "Boston"
    assert by_name["f_city"].confidence == pytest.approx(0.95)
    assert "Direct match" in by_name["f_city"].reason


def test_ambiguous_coercion_is_flagged_not_written():
    fields = [
        EnrichedFormField(
            field=FormField(name="f_dob", field_type="text", page_number=1),
            semantics=FieldSemantics(
                semantic_meaning="date_of_birth",
                expected_data_type="date",
                confidence_score=0.9,
            ),
        )
    ]
    result = map_user_data_to_fields(fields, {"dob": "not-a-date"}, strict=True)
    assert result.decisions[0].requires_review is True


def test_override_precedence_and_confidence_are_stable():
    fields = [_field("f_city", "city")]
    result = map_user_data_to_fields(
        fields, {"city": "Boston"}, strict=True, overrides={"f_city": "Cambridge"}
    )
    decision = result.decisions[0]
    assert decision.selected_value == "Cambridge"
    assert decision.confidence == 1.0
    assert decision.requires_review is False


def test_key_reuse_behaviour_is_stable():
    fields = [_field("a", "first_name"), _field("b", "first_name")]

    reused = map_user_data_to_fields(fields, {"firstname": "Jane"}, strict=True)
    assert sorted(d.field_name for d in reused.decisions) == ["a", "b"]

    once = map_user_data_to_fields(
        fields, {"firstname": "Jane"}, strict=True, allow_key_reuse=False
    )
    assert [d.field_name for d in once.decisions] == ["a"]


def test_unmapped_keys_are_reported_with_dotted_paths():
    fields = [_field("f_city", "city")]
    result = map_user_data_to_fields(
        fields, {"address": {"city": "Boston", "zip": "02101"}}, strict=True
    )
    assert result.decisions[0].selected_value == "Boston"
    assert result.unmapped_user_keys == ["address.zip"]


def test_mapping_is_stable_across_repeated_runs():
    """Same inputs, same decisions — including ordering."""
    fields = [_field("f_first", "first_name"), _field("f_city", "city"), _field("f_zip", "postal_code")]
    data = {"firstname": "Jane", "city": "Boston", "zip": "02101"}

    runs = [
        [
            (d.field_name, d.selected_value, round(d.confidence, 4), d.requires_review)
            for d in map_user_data_to_fields(fields, dict(data), strict=True).decisions
        ]
        for _ in range(5)
    ]
    assert all(run == runs[0] for run in runs)
