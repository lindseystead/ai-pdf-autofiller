"""
Tests for the commands that close the loop: init, extract, and CSV batch.

Together these remove the manual steps around a fill — writing the data file by
hand, re-keying a form someone already completed, and converting a spreadsheet
into JSON.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_autofiller.cli import main
from pdf_autofiller.mapping import flatten_user_data
from pdf_autofiller.pipeline import extract_form_values
from pdf_autofiller.settings import Settings, set_settings

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "sample_form.pdf"
COMPLETE = {
    "firstname": "Jane",
    "lastname": "Doe",
    "dob": "1990-01-01",
    "email": "jane@example.com",
    "phone": "555-0100",
}


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path):
    set_settings(Settings(state_dir=tmp_path / "state", auth_enabled=False))
    yield
    set_settings(None)


@pytest.fixture
def filled(tmp_path) -> Path:
    target = tmp_path / "filled.pdf"
    data = tmp_path / "d.json"
    data.write_text(json.dumps(COMPLETE), encoding="utf-8")
    assert main(["fill", str(SAMPLE), "--data", str(data), "--out", str(target)]) == 0
    return target


# --- init ------------------------------------------------------------------


def test_init_emits_a_data_file_with_the_forms_keys(capsys):
    assert main(["init", str(SAMPLE)]) == 0
    skeleton = json.loads(capsys.readouterr().out)
    assert set(skeleton) == {"firstname", "lastname", "dob", "email", "phone"}
    assert all(value == "" for value in skeleton.values())


def test_init_puts_required_keys_first():
    """Ordering is the whole point: the keys you must supply are at the top."""
    from pdf_autofiller.pipeline import data_skeleton

    skeleton, annotations = data_skeleton(SAMPLE)
    keys = list(skeleton)
    required = [k for k in keys if annotations[k]["required"]]
    assert keys[: len(required)] == required


def test_init_output_is_directly_usable_as_data(tmp_path, capsys):
    """The skeleton must round-trip through fill without hand-editing its shape."""
    main(["init", str(SAMPLE)])
    skeleton = json.loads(capsys.readouterr().out)
    skeleton.update(COMPLETE)
    data = tmp_path / "d.json"
    data.write_text(json.dumps(skeleton), encoding="utf-8")

    out = tmp_path / "o.pdf"
    assert main(["fill", str(SAMPLE), "--data", str(data), "--out", str(out)]) == 0
    assert out.exists()


def test_init_annotate_describes_each_key(capsys):
    assert main(["init", str(SAMPLE), "--annotate"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["_fields"]["firstname"]["fields"] == ["txtFirstName"]
    assert payload["_fields"]["firstname"]["required"] is True
    assert payload["firstname"] == ""


def test_annotation_block_is_ignored_when_used_as_data():
    """JSON has no comments, so annotations ride along under `_fields`.

    They must not come back as dozens of unmapped keys burying the real ones.
    """
    flat = flatten_user_data({"_fields": {"a": {"required": True}}, "firstname": "Jane"})
    assert flat == {"firstname": "Jane"}


def test_init_on_a_form_with_no_fields_fails(tmp_path, capsys):
    from pypdf import PdfWriter

    blank = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with blank.open("wb") as handle:
        writer.write(handle)

    assert main(["init", str(blank)]) == 1
    assert "no fillable form fields" in capsys.readouterr().err


# --- extract ---------------------------------------------------------------


def test_extract_reads_values_back_out(filled, capsys):
    assert main(["extract", str(filled)]) == 0
    assert json.loads(capsys.readouterr().out) == COMPLETE


def test_extract_raw_keys_by_field_name(filled, capsys):
    assert main(["extract", str(filled), "--raw"]) == 0
    values = json.loads(capsys.readouterr().out)
    assert values["txtFirstName"] == "Jane"
    assert "firstname" not in values


def test_extract_output_round_trips_back_into_fill(filled, tmp_path, capsys):
    """The default keying must be the shape that feeds --data, or it is useless."""
    main(["extract", str(filled)])
    extracted = tmp_path / "extracted.json"
    extracted.write_text(capsys.readouterr().out, encoding="utf-8")

    out = tmp_path / "refilled.pdf"
    assert main(["fill", str(SAMPLE), "--data", str(extracted), "--out", str(out)]) == 0
    capsys.readouterr()  # discard the fill summary before reading the next command

    assert main(["extract", str(out)]) == 0
    assert json.loads(capsys.readouterr().out) == COMPLETE


def test_extract_omits_empty_fields_by_default(tmp_path):
    """A blank field means "not answered"; carrying "" forward would overwrite."""
    partial = tmp_path / "partial.pdf"
    data = tmp_path / "p.json"
    data.write_text(json.dumps({**COMPLETE, "phone": "555"}), encoding="utf-8")
    main(["fill", str(SAMPLE), "--data", str(data), "--out", str(partial)])

    values = extract_form_values(partial)
    assert "" not in values.values()


def test_extract_include_empty_keeps_blank_fields(filled):
    lean = extract_form_values(filled)
    full = extract_form_values(filled, include_empty=True)
    assert set(lean) <= set(full)


def test_extract_save_profile_makes_a_reusable_profile(filled, tmp_path, capsys):
    """A form someone filled by hand becomes reusable data in one step."""
    assert main(["extract", str(filled), "--save-profile", "jane"]) == 0
    assert "saved profile jane" in capsys.readouterr().out

    out = tmp_path / "viaprofile.pdf"
    assert main(["fill", str(SAMPLE), "--profile", "jane", "--out", str(out)]) == 0
    assert out.exists()


def test_extract_on_an_unfilled_form_is_empty(capsys):
    assert main(["extract", str(SAMPLE)]) == 0
    assert json.loads(capsys.readouterr().out) == {}


def test_extract_keeps_first_value_on_semantic_collision(tmp_path):
    """Two fields meaning the same thing must not depend on field order."""
    from pdf_autofiller.models import DocumentMetadata, DocumentStructure, FormField
    from pdf_autofiller import pipeline

    structure = DocumentStructure(
        metadata=DocumentMetadata(num_pages=1),
        form_fields=[
            FormField(name="txtDate", field_type="text", value="first", page_number=1),
            FormField(name="txt_date", field_type="text", value="second", page_number=1),
        ],
    )
    original = pipeline.read_pdf
    pipeline.read_pdf = lambda *a, **k: structure
    try:
        assert extract_form_values(tmp_path / "irrelevant.pdf") == {"date": "first"}
    finally:
        pipeline.read_pdf = original


# --- batch --csv -----------------------------------------------------------


def _csv(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "rows.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_batch_csv_fills_one_document_per_row(tmp_path, capsys):
    rows = _csv(
        tmp_path,
        "name,firstname,lastname,dob,email,phone\n"
        "alice,Alice,Ng,1988-02-03,a@x.com,555-1\n"
        "bob,Bob,Ray,1991-07-09,b@x.com,555-2\n",
    )
    out_dir = tmp_path / "out"
    assert main(["batch", str(SAMPLE), "--csv", str(rows), "--out-dir", str(out_dir)]) == 0
    assert (out_dir / "alice_filled.pdf").exists()
    assert (out_dir / "bob_filled.pdf").exists()


def test_batch_csv_without_a_name_column_numbers_rows(tmp_path):
    rows = _csv(
        tmp_path,
        "firstname,lastname,dob,email,phone\nAlice,Ng,1988-02-03,a@x.com,555-1\n",
    )
    out_dir = tmp_path / "out"
    assert main(["batch", str(SAMPLE), "--csv", str(rows), "--out-dir", str(out_dir)]) == 0
    assert (out_dir / "row-1_filled.pdf").exists()


def test_batch_csv_continues_past_a_failing_row(tmp_path, capsys):
    rows = _csv(
        tmp_path,
        "name,firstname,lastname,dob,email,phone\n"
        "alice,Alice,Ng,1988-02-03,a@x.com,555-1\n"
        "broken,OnlyFirst,,,,\n",
    )
    out_dir = tmp_path / "out"
    exit_code = main(
        ["--json", "batch", str(SAMPLE), "--csv", str(rows), "--out-dir", str(out_dir)]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert payload["total"] == 2 and payload["failed"] == 1
    assert (out_dir / "alice_filled.pdf").exists()


def test_batch_csv_drops_empty_cells(tmp_path):
    """An empty cell means "not supplied", not "set this to empty"."""
    rows = _csv(tmp_path, "name,firstname,lastname\nx,Jane,\n")
    from pdf_autofiller.cli import _read_batch_items
    import argparse

    args = argparse.Namespace(csv=str(rows), items=None)
    assert _read_batch_items(args) == [{"name": "x", "user_data": {"firstname": "Jane"}}]


def test_batch_csv_handles_a_utf8_bom(tmp_path):
    """Spreadsheet exports routinely carry a BOM; it must not corrupt the first key."""
    path = tmp_path / "bom.csv"
    path.write_text("name,firstname\nx,Jane\n", encoding="utf-8-sig")
    from pdf_autofiller.cli import _read_batch_items
    import argparse

    items = _read_batch_items(argparse.Namespace(csv=str(path), items=None))
    assert items == [{"name": "x", "user_data": {"firstname": "Jane"}}]


def test_batch_rejects_a_headerless_or_empty_csv(tmp_path):
    from pdf_autofiller.cli import _read_batch_items
    import argparse

    empty = _csv(tmp_path, "")
    with pytest.raises(SystemExit):
        _read_batch_items(argparse.Namespace(csv=str(empty), items=None))

    header_only = _csv(tmp_path, "name,firstname\n")
    with pytest.raises(SystemExit):
        _read_batch_items(argparse.Namespace(csv=str(header_only), items=None))


def test_batch_requires_exactly_one_source(tmp_path):
    rows = _csv(tmp_path, "name,firstname\nx,Jane\n")
    with pytest.raises(SystemExit):
        main(["batch", str(SAMPLE), "--csv", str(rows), "--items", "x.json"])
    with pytest.raises(SystemExit):
        main(["batch", str(SAMPLE)])
