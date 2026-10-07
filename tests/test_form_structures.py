"""Regression tests for real-world AcroForm structures.

Each test pins a failure found in an adversarial review: radio groups,
hierarchical names, nested JSON, verbatim dates, partial fills, /MaxLen,
flatten cleanup, and unfilled-field reporting.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfReader

from pdf_autofiller import fill, fill_detailed, preview
from pdf_autofiller.field_utils import field_leaf_name
from pdf_autofiller.pdf_writer import UnresolvedRequiredFieldsError
from pdf_autofiller.user_data import UserDataTooDeepError, flatten_user_data

from .form_factory import FormBuilder


def _values(path: Path) -> dict[str, object]:
    return {name: field.get("/V") for name, field in (PdfReader(path).get_fields() or {}).items()}


@pytest.fixture
def intake_pdf(tmp_path: Path) -> Path:
    return (
        FormBuilder(pages=2)
        .text("firstName", parent="applicant")
        .text("lastName", parent="applicant", required=True)
        .text("DOB")
        .text("ssn", max_len=9)
        .radio("gender", ["Male", "Female"], required=True)
        .checkbox("agree_terms")
        .text("phone", page=1)
        .save(tmp_path / "intake.pdf")
    )


def test_required_radio_group_accepts_option_name(intake_pdf: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    report = fill(intake_pdf, {"last_name": "Doe", "gender": "Female"}, out)
    assert "gender" in report.written_fields
    assert _values(out)["gender"] == "/Female"


def test_radio_unknown_option_is_reported_unwritable(intake_pdf: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    with pytest.raises(UnresolvedRequiredFieldsError):
        fill(intake_pdf, {"last_name": "Doe", "gender": "Other"}, out)
    report = fill(intake_pdf, {"last_name": "Doe", "gender": "Other"}, out, allow_partial=True)
    unwritable = report.skipped_unwritable_fields
    assert any(item.startswith("gender (unresolved_button_state") for item in unwritable)
    assert "gender" in report.missing_required_fields


def test_hierarchical_names_match_by_leaf(intake_pdf: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    fill(intake_pdf, {"first_name": "Jane", "last_name": "Doe", "gender": "Male"}, out)
    values = _values(out)
    assert values["applicant.firstName"] == "Jane"
    assert values["applicant.lastName"] == "Doe"


def test_nested_json_matches_full_path_and_unique_leaf(intake_pdf: Path) -> None:
    result = preview(
        intake_pdf,
        {"applicant": {"firstName": "Jane", "lastName": "Doe"}, "contact": {"phone": "555"}},
    )
    selected = {d.field_name: d.selected_value for d in result.mapping.decisions}
    assert selected["applicant.firstName"] == "Jane"
    assert selected["applicant.lastName"] == "Doe"
    assert selected["phone"] == "555"  # unique leaf of contact.phone
    assert result.mapping.unmapped_user_keys == []


def test_ambiguous_nested_leaf_is_not_guessed() -> None:
    flat = flatten_user_data({"home": {"city": "A"}, "work": {"city": "B"}, "tags": ["x"]})
    assert flat.values == {"home.city": "A", "work.city": "B", "tags.0": "x"}
    assert "city" not in flat.leaf_aliases


def test_flatten_rejects_excessive_depth() -> None:
    deep: dict = {}
    node = deep
    for _ in range(40):
        node["a"] = {}
        node = node["a"]
    with pytest.raises(UserDataTooDeepError):
        flatten_user_data(deep)


@pytest.mark.parametrize(
    ("name", "leaf"),
    [
        ("applicant.firstName", "firstName"),
        ("form1[0].Page1[0].LastName[0]", "LastName"),
        ("txtFirstName", "txtFirstName"),
    ],
)
def test_field_leaf_name(name: str, leaf: str) -> None:
    assert field_leaf_name(name) == leaf


def test_dates_are_written_verbatim(intake_pdf: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    fill(intake_pdf, {"last_name": "Doe", "gender": "Male", "dob": "03/04/1990"}, out)
    assert _values(out)["DOB"] == "03/04/1990"


def test_value_over_max_length_is_not_written(intake_pdf: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    report = fill(intake_pdf, {"last_name": "Doe", "gender": "Male", "ssn": "123-45-6789"}, out)
    assert "ssn (exceeds_max_length:9)" in report.skipped_unwritable_fields
    assert "ssn" not in report.written_fields


def test_allow_partial_writes_pdf_and_lists_missing(intake_pdf: Path, tmp_path: Path) -> None:
    out = tmp_path / "out.pdf"
    report = fill(intake_pdf, {"first_name": "Jane"}, out, allow_partial=True)
    assert out.exists()
    assert report.missing_required_fields == ["applicant.lastName", "gender"]
    assert _values(out)["applicant.firstName"] == "Jane"


def test_report_lists_unfilled_fields(intake_pdf: Path, tmp_path: Path) -> None:
    outcome = fill_detailed(intake_pdf, {"last_name": "Doe", "gender": "Male"}, tmp_path / "out.pdf")
    assert set(outcome.report.unfilled_fields) == {
        "applicant.firstName",
        "DOB",
        "ssn",
        "agree_terms",
        "phone",
    }


def test_flatten_removes_acroform_and_stays_readable(intake_pdf: Path, tmp_path: Path) -> None:
    out = tmp_path / "flat.pdf"
    fill(
        intake_pdf,
        {"first_name": "Jane", "last_name": "Doe", "gender": "Male", "phone": "555"},
        out,
        flatten=True,
    )
    reader = PdfReader(out)
    assert "/AcroForm" not in reader.trailer["/Root"]
    assert reader.get_fields() is None
    assert "Jane" in reader.pages[0].extract_text()
    assert "555" in reader.pages[1].extract_text()
