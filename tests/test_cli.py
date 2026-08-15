"""Tests for the command-line interface."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pdf_autofiller.cli import main
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


def _data_file(tmp_path: Path, payload: dict) -> str:
    path = tmp_path / "data.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def test_validate_reports_field_counts(capsys):
    assert main(["validate", str(SAMPLE)]) == 0
    out = capsys.readouterr().out
    assert "5 fields" in out
    assert "fingerprint" in out


def test_validate_fails_on_a_form_with_no_fields(tmp_path, capsys):
    from pypdf import PdfWriter

    blank = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with blank.open("wb") as handle:
        writer.write(handle)

    assert main(["validate", str(blank)]) == 1
    assert "no fillable form fields" in capsys.readouterr().out


def test_inspect_shows_fields_without_writing_anything(tmp_path, capsys):
    """Discovery must not require attempting a fill."""
    before = set(tmp_path.iterdir())
    assert main(["inspect", str(SAMPLE), "--set", "firstname=Jane"]) == 0
    out = capsys.readouterr().out
    assert "txtFirstName" in out
    assert "'Jane'" in out
    assert "missing required" in out
    assert set(tmp_path.iterdir()) == before


def test_inspect_json_output_is_machine_readable(capsys):
    assert main(["--json", "inspect", str(SAMPLE)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["fields"]) == 5
    assert payload["fingerprint"]


def test_fill_writes_output_and_reports_counts(tmp_path, capsys):
    out = tmp_path / "filled.pdf"
    assert main(["fill", str(SAMPLE), "--data", _data_file(tmp_path, COMPLETE), "--out", str(out)]) == 0
    assert out.exists() and out.read_bytes().startswith(b"%PDF")
    assert "5/5 fields" in capsys.readouterr().out


def test_fill_flatten_removes_the_interactive_form(tmp_path):
    from pypdf import PdfReader

    out = tmp_path / "flat.pdf"
    main(["fill", str(SAMPLE), "--data", _data_file(tmp_path, COMPLETE),
          "--out", str(out), "--flatten"])
    reader = PdfReader(str(out))
    assert "/AcroForm" not in reader.trailer["/Root"]
    widgets = [
        annot
        for page in reader.pages
        for annot in (page.get("/Annots") or [])
        if annot.get_object().get("/Subtype") == "/Widget"
    ]
    assert widgets == []
    assert "Jane" in (reader.pages[0].extract_text() or "")


def test_fill_accepts_nested_profile_data(tmp_path, capsys):
    nested = {
        "firstname": "Jane",
        "lastname": "Doe",
        "dob": "1990-01-01",
        "contact": {"email": "jane@example.com", "phone": "555-0100"},
    }
    out = tmp_path / "nested.pdf"
    assert main(["fill", str(SAMPLE), "--data", _data_file(tmp_path, nested), "--out", str(out)]) == 0
    assert "5/5 fields" in capsys.readouterr().out


def test_set_flag_overrides_data_file(tmp_path, capsys):
    out = tmp_path / "o.pdf"
    main(["--json", "fill", str(SAMPLE), "--data", _data_file(tmp_path, COMPLETE),
          "--set", "firstname=Override", "--out", str(out)])
    assert json.loads(capsys.readouterr().out)["report"]["written_fields"]


def test_missing_required_field_exits_with_typed_error(tmp_path, capsys):
    code = main(["fill", str(SAMPLE), "--set", "firstname=Jane", "--out", str(tmp_path / "x.pdf")])
    assert code == 2
    assert "required_fields_unresolved" in capsys.readouterr().err


def test_profile_and_template_round_trip_through_cli(tmp_path, capsys):
    assert main(["profile", "set", "me", "--data", _data_file(tmp_path, COMPLETE)]) == 0
    assert main(["template", "save", "sample", str(SAMPLE), "--flatten"]) == 0

    out = tmp_path / "viaprofile.pdf"
    assert main(["fill", str(SAMPLE), "--profile", "me", "--template", "sample",
                 "--out", str(out)]) == 0
    assert out.exists()

    capsys.readouterr()
    assert main(["profile", "list"]) == 0
    assert "me" in capsys.readouterr().out


def test_batch_continues_past_a_failing_row(tmp_path, capsys):
    rows = [
        {"name": "alice", "user_data": COMPLETE},
        {"name": "broken", "user_data": {"firstname": "OnlyFirst"}},
        {"name": "bob", "user_data": COMPLETE},
    ]
    items = tmp_path / "rows.json"
    items.write_text(json.dumps(rows), encoding="utf-8")
    out_dir = tmp_path / "filled"

    exit_code = main(["--json", "batch", str(SAMPLE), "--items", str(items),
                      "--out-dir", str(out_dir)])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 1  # non-zero because something failed
    assert payload["total"] == 3 and payload["failed"] == 1
    assert (out_dir / "alice_filled.pdf").exists()
    assert (out_dir / "bob_filled.pdf").exists()
    assert not (out_dir / "broken_filled.pdf").exists()


def test_bad_json_data_file_is_a_clean_error(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["fill", str(SAMPLE), "--data", str(bad)])
    assert "not valid JSON" in str(exc.value)


def test_set_without_equals_is_rejected(tmp_path):
    with pytest.raises(SystemExit) as exc:
        main(["fill", str(SAMPLE), "--set", "novalue"])
    assert "key=value" in str(exc.value)
