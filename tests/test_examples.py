"""Smoke-test the runnable examples so README snippets don't rot."""

import runpy
import sys
from pathlib import Path

from pypdf import PdfReader

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_quickstart_example_writes_filled_pdf(tmp_path, monkeypatch, capsys):
    output = tmp_path / "filled.pdf"
    monkeypatch.setattr(sys, "argv", ["quickstart.py", str(output)])

    namespace = runpy.run_path(str(EXAMPLES / "quickstart.py"))
    assert namespace["main"](sys.argv) == 0

    values = {name: field.get("/V") for name, field in PdfReader(output).get_fields().items()}
    assert values["txtFirstName"] == "Jane"
    assert values["txtLastName"] == "Doe"
    assert "Wrote" in capsys.readouterr().out
