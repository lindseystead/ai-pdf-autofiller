"""Tests for PDF reader extraction helpers and main flow."""

from pathlib import Path

import pytest

from pdf_autofiller import pdf_reader


class FakeRef:
    """Simple reference wrapper mimicking pypdf indirect objects."""

    def __init__(self, obj):
        self._obj = obj

    def get_object(self):
        return self._obj


class FakePage(dict):
    """Page object with optional extract_text behavior."""

    def __init__(self, text=None, *, raise_on_extract=False, **kwargs):
        super().__init__(**kwargs)
        self._text = text
        self._raise_on_extract = raise_on_extract

    def extract_text(self):
        if self._raise_on_extract:
            raise RuntimeError("text extraction failed")
        return self._text


def test_read_pdf_enforces_page_limit(tmp_path):
    """read_pdf rejects documents exceeding max_pages before extraction."""
    from pypdf import PdfWriter

    pdf_path = tmp_path / "multi.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.add_blank_page(width=200, height=200)
    with open(pdf_path, "wb") as handle:
        writer.write(handle)

    with pytest.raises(pdf_reader.PdfPageLimitError) as exc_info:
        pdf_reader.read_pdf(pdf_path, max_pages=1)

    assert exc_info.value.num_pages == 2
    assert exc_info.value.max_pages == 1


def test_read_pdf_allows_within_page_limit(tmp_path):
    from pypdf import PdfWriter

    pdf_path = tmp_path / "single.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    with open(pdf_path, "wb") as handle:
        writer.write(handle)

    structure = pdf_reader.read_pdf(pdf_path, max_pages=5)
    assert structure.metadata.num_pages == 1


def test_extract_text_regions_enforces_total_char_budget(monkeypatch):
    """Total extracted text is bounded to limit memory/provider exposure."""
    import types

    monkeypatch.setattr(pdf_reader, "MAX_TOTAL_TEXT_CHARS", 10)
    reader = types.SimpleNamespace(
        pages=[FakePage(text="A" * 8), FakePage(text="B" * 8), FakePage(text="C" * 8)]
    )

    regions = pdf_reader._extract_text_regions(reader)

    total = sum(len(region.text) for region in regions)
    assert total <= 10


def test_extract_text_regions_skips_bad_pages():
    pages = [
        FakePage("  First page text  "),
        FakePage(None),
        FakePage(raise_on_extract=True),
    ]

    class FakeReader:
        def __init__(self, pages):
            self.pages = pages

    regions = pdf_reader._extract_text_regions(FakeReader(pages))
    assert len(regions) == 1
    assert regions[0].text == "First page text"
    assert regions[0].page_number == 1


def test_read_pdf_raises_for_missing_file():
    with pytest.raises(FileNotFoundError):
        pdf_reader.read_pdf(Path("/tmp/does-not-exist-xyz.pdf"))


def test_read_pdf_returns_document_structure(monkeypatch, tmp_path):
    pdf_path = tmp_path / "dummy.pdf"
    pdf_path.write_bytes(b"%PDF-1.7")

    class FakeReader:
        def __init__(self, _):
            self.metadata = {
                "/Title": "My Form",
                "/Author": "Alex",
                "/Subject": object(),
                "/Creator": "Test Suite",
                "/Producer": "pypdf",
            }
            self.pages = [FakePage("Page text")]

        @staticmethod
        def get_fields():
            return {
                "txtLastName": {
                    "/FT": "/Tx",
                    "/V": "Stead",
                    "/Ff": 0x02,
                }
            }

    monkeypatch.setattr(pdf_reader, "PdfReader", FakeReader)

    structure = pdf_reader.read_pdf(pdf_path)
    assert structure.metadata.num_pages == 1
    assert structure.metadata.title == "My Form"
    assert structure.metadata.author == "Alex"
    assert structure.metadata.subject is None
    assert len(structure.form_fields) == 1
    assert structure.form_fields[0].name == "txtLastName"
    assert len(structure.text_regions) == 1


def test_read_pdf_malformed_info_dictionary_raises_invalid_pdf(tmp_path):
    """A trailer /Info that is not a dictionary is a client error, not a crash."""
    import io
    import re

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    buffer = io.BytesIO()
    writer.write(buffer)
    data = buffer.getvalue()
    info_obj = re.search(rb"/Info (\d+) 0 R", data).group(1)
    data = re.sub(rb"(\n" + info_obj + rb" 0 obj\n)<<.*?>>", rb"\g<1>5", data, flags=re.S)
    path = tmp_path / "bad_info.pdf"
    path.write_bytes(data)

    with pytest.raises(pdf_reader.InvalidPdfError):
        pdf_reader.read_pdf(path)
