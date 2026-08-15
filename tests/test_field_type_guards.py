"""
The writer must only write values a field can legally hold.

Only checkboxes and radios were translated before. Choice fields took any string,
including values outside their declared options, and signature fields were
written as plain text — which cannot produce a valid signature and destroys an
existing one. Both now land in ``skipped_invalid_fields`` instead of the PDF.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from pdf_autofiller.acroform_fields import choice_options, field_options
from pdf_autofiller.models import FieldMappingDecision, MappingResult
from pdf_autofiller.pdf_writer import fill_pdf


def _decision(field_name: str, value: str) -> FieldMappingDecision:
    return FieldMappingDecision(
        field_name=field_name,
        semantic_meaning="test",
        selected_value=value,
        confidence=0.95,
        reason="test",
        requires_review=False,
    )


def _form_pdf(tmp_path: Path, fields: list[DictionaryObject]) -> Path:
    """Build a one-page PDF whose AcroForm holds the given field dictionaries."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    annots = ArrayObject()
    for field in fields:
        field[NameObject("/Type")] = NameObject("/Annot")
        field[NameObject("/Subtype")] = NameObject("/Widget")
        field[NameObject("/Rect")] = ArrayObject(
            [NumberObject(10), NumberObject(10), NumberObject(200), NumberObject(30)]
        )
        ref = writer._add_object(field)
        annots.append(ref)
    page[NameObject("/Annots")] = annots
    writer._root_object[NameObject("/AcroForm")] = writer._add_object(
        DictionaryObject({NameObject("/Fields"): annots})
    )
    target = tmp_path / "form.pdf"
    with target.open("wb") as handle:
        writer.write(handle)
    return target


def _choice_field(name: str, options: list[str]) -> DictionaryObject:
    return DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Ch"),
            NameObject("/T"): TextStringObject(name),
            NameObject("/Opt"): ArrayObject([TextStringObject(o) for o in options]),
        }
    )


def _signature_field(name: str) -> DictionaryObject:
    return DictionaryObject(
        {NameObject("/FT"): NameObject("/Sig"), NameObject("/T"): TextStringObject(name)}
    )


def _text_field(name: str) -> DictionaryObject:
    return DictionaryObject(
        {NameObject("/FT"): NameObject("/Tx"), NameObject("/T"): TextStringObject(name)}
    )


def test_choice_value_within_options_is_written(tmp_path):
    source = _form_pdf(tmp_path, [_choice_field("ddState", ["MA", "NY", "CA"])])
    out = tmp_path / "out.pdf"
    report = fill_pdf(source, out, MappingResult(decisions=[_decision("ddState", "NY")]))

    assert report.written_fields == ["ddState"]
    assert report.skipped_invalid_fields == []
    assert str(PdfReader(str(out)).get_fields()["ddState"].get("/V")) == "NY"


def test_choice_value_outside_options_is_skipped(tmp_path):
    """An out-of-range choice produces a document viewers may render blank."""
    source = _form_pdf(tmp_path, [_choice_field("ddState", ["MA", "NY"])])
    out = tmp_path / "out.pdf"
    report = fill_pdf(source, out, MappingResult(decisions=[_decision("ddState", "Atlantis")]))

    assert report.written_fields == []
    assert report.skipped_invalid_fields == ["ddState"]


def test_choice_matching_is_case_insensitive(tmp_path):
    source = _form_pdf(tmp_path, [_choice_field("ddState", ["Massachusetts"])])
    out = tmp_path / "out.pdf"
    report = fill_pdf(source, out, MappingResult(decisions=[_decision("ddState", "massachusetts")]))

    assert report.written_fields == ["ddState"]
    # The declared spelling is what gets written, not the caller's casing.
    assert str(PdfReader(str(out)).get_fields()["ddState"].get("/V")) == "Massachusetts"


def test_signature_field_is_never_written(tmp_path):
    """Writing text into /Sig cannot make a signature and invalidates a real one."""
    source = _form_pdf(tmp_path, [_signature_field("sigApplicant")])
    out = tmp_path / "out.pdf"
    report = fill_pdf(source, out, MappingResult(decisions=[_decision("sigApplicant", "Jane Doe")]))

    assert report.written_fields == []
    assert report.skipped_invalid_fields == ["sigApplicant"]
    assert PdfReader(str(out)).get_fields()["sigApplicant"].get("/V") is None


def test_free_text_choice_without_options_accepts_anything(tmp_path):
    """A combo box with no /Opt is free text; it must not be over-restricted."""
    field = DictionaryObject(
        {NameObject("/FT"): NameObject("/Ch"), NameObject("/T"): TextStringObject("cbAny")}
    )
    source = _form_pdf(tmp_path, [field])
    out = tmp_path / "out.pdf"
    report = fill_pdf(source, out, MappingResult(decisions=[_decision("cbAny", "whatever")]))
    assert report.written_fields == ["cbAny"]


def test_one_invalid_field_does_not_block_the_others(tmp_path):
    source = _form_pdf(
        tmp_path,
        [_text_field("txtName"), _choice_field("ddState", ["MA"]), _signature_field("sig")],
    )
    out = tmp_path / "out.pdf"
    report = fill_pdf(
        source,
        out,
        MappingResult(
            decisions=[
                _decision("txtName", "Jane"),
                _decision("ddState", "Nowhere"),
                _decision("sig", "Jane"),
            ]
        ),
    )
    assert report.written_fields == ["txtName"]
    assert sorted(report.skipped_invalid_fields) == ["ddState", "sig"]


def test_choice_options_are_exposed_on_extracted_fields(tmp_path):
    """Callers cannot supply a legal value without being told what the options are."""
    from pdf_autofiller.pdf_reader import read_pdf

    source = _form_pdf(tmp_path, [_choice_field("ddState", ["MA", "NY", "CA"])])
    structure = read_pdf(source)
    field = next(f for f in structure.form_fields if f.name == "ddState")
    assert field.options == ["MA", "NY", "CA"]


def test_choice_options_unwraps_export_display_pairs():
    field = DictionaryObject(
        {
            NameObject("/FT"): NameObject("/Ch"),
            NameObject("/Opt"): ArrayObject(
                [
                    ArrayObject([TextStringObject("MA"), TextStringObject("Massachusetts")]),
                    TextStringObject("NY"),
                ]
            ),
        }
    )
    # The export value is what must be written, not the display label.
    assert choice_options(field) == ["MA", "NY"]
    assert field_options(field) == ["MA", "NY"]


def test_field_options_empty_for_plain_text():
    assert field_options(_text_field("txtName")) == []


def test_report_distinguishes_skip_reasons(tmp_path):
    source = _form_pdf(tmp_path, [_text_field("a"), _text_field("b"), _choice_field("c", ["x"])])
    out = tmp_path / "out.pdf"
    report = fill_pdf(
        source,
        out,
        MappingResult(
            decisions=[
                FieldMappingDecision(
                    field_name="a", semantic_meaning="s", selected_value="v",
                    confidence=0.5, reason="low", requires_review=True,
                ),
                FieldMappingDecision(
                    field_name="b", semantic_meaning="s", selected_value=None,
                    confidence=0.9, reason="none", requires_review=False,
                ),
                _decision("c", "not-an-option"),
            ]
        ),
    )
    assert report.skipped_review_fields == ["a"]
    assert report.skipped_empty_fields == ["b"]
    assert report.skipped_invalid_fields == ["c"]
