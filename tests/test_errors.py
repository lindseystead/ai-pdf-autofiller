"""Every error the library raises on purpose shares one catchable base."""

from __future__ import annotations

from pathlib import Path

import pytest

import pdf_autofiller
from pdf_autofiller import PdfAutofillerError, fill, preview


@pytest.mark.parametrize(
    "name",
    [
        "InvalidPdfError",
        "PdfPageLimitError",
        "UnresolvedRequiredFieldsError",
        "UserDataTooDeepError",
        "PDFAutofillError",
    ],
)
def test_public_errors_are_exported_and_share_the_base(name):
    error_type = getattr(pdf_autofiller, name)
    assert issubclass(error_type, PdfAutofillerError)
    assert name in pdf_autofiller.__all__


def test_value_errors_stay_value_errors():
    # Callers that already catch ValueError must keep working.
    assert issubclass(pdf_autofiller.InvalidPdfError, ValueError)
    assert issubclass(pdf_autofiller.UserDataTooDeepError, ValueError)


def test_one_except_clause_catches_each_failure_mode(tmp_path: Path):
    not_a_pdf = tmp_path / "x.pdf"
    not_a_pdf.write_bytes(b"hello")
    deep: dict = {}
    node = deep
    for _ in range(40):
        node["a"] = {}
        node = node["a"]
    failures = [
        lambda: preview(not_a_pdf, {}),
        lambda: preview("samples/sample_form.pdf", deep),
        lambda: preview("samples/sample_form.pdf", {}, max_pages=0),
        lambda: fill("samples/sample_form.pdf", {}, tmp_path / "out.pdf"),
    ]
    for failure in failures:
        with pytest.raises(PdfAutofillerError):
            failure()
