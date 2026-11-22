"""Smoke-test the runnable examples so README snippets don't rot."""

import runpy
import sys
from pathlib import Path

from pypdf import PdfReader

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_batch_example_writes_one_pdf_per_contractor(tmp_path, monkeypatch, capsys):
    output_dir = tmp_path / "contractors"
    monkeypatch.setattr(sys, "argv", ["batch_fill.py", str(output_dir)])

    namespace = runpy.run_path(str(EXAMPLES / "batch_fill.py"))
    assert namespace["main"](sys.argv) == 0

    doe = {name: field.get("/V") for name, field in PdfReader(output_dir / "Doe.pdf").get_fields().items()}
    lee = {name: field.get("/V") for name, field in PdfReader(output_dir / "Lee.pdf").get_fields().items()}
    assert doe["txtFirstName"] == "Jane"
    assert lee["txtLastName"] == "Lee"
    assert "Wrote 2" in capsys.readouterr().out


def test_quickstart_example_writes_filled_pdf(tmp_path, monkeypatch, capsys):
    output = tmp_path / "filled.pdf"
    monkeypatch.setattr(sys, "argv", ["quickstart.py", str(output)])

    namespace = runpy.run_path(str(EXAMPLES / "quickstart.py"))
    assert namespace["main"](sys.argv) == 0

    values = {name: field.get("/V") for name, field in PdfReader(output).get_fields().items()}
    assert values["txtFirstName"] == "Jane"
    assert values["txtLastName"] == "Doe"
    assert "Wrote" in capsys.readouterr().out
