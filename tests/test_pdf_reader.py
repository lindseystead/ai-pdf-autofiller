"""Tests for PDF reader extraction helpers and main flow."""

from pathlib import Path

import pytest
from pypdf.generic import IndirectObject

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


def test_get_field_type_variants():
    assert pdf_reader._get_field_type({"/FT": "/Tx"}) == "text"
    assert pdf_reader._get_field_type({"/FT": "/Btn"}) == "button"
    assert pdf_reader._get_field_type({"/FT": "/Ch"}) == "choice"
    assert pdf_reader._get_field_type({"/FT": "/Sig"}) == "signature"
    assert pdf_reader._get_field_type({"/FT": "/Other"}) == "unknown"


def test_get_field_value_handles_direct_values():
    assert pdf_reader._get_field_value({"/V": "hello"}) == "hello"
    assert pdf_reader._get_field_value({"/V": 123}) == "123"
    assert pdf_reader._get_field_value({"/V": True}) == "True"
    assert pdf_reader._get_field_value({"/V": None}) is None


def test_get_field_value_handles_reference_resolution(monkeypatch):
    class FakeIndirect(IndirectObject):
        def __init__(self, value):
            self._value = value

        def get_object(self):
            return self._value

    assert pdf_reader._get_field_value({"/V": FakeIndirect("resolved")}) == "resolved"

    class BrokenIndirect(IndirectObject):
        def get_object(self):
            raise RuntimeError("broken")

        def __str__(self):
            return "<broken-indirect>"

    value = pdf_reader._get_field_value({"/V": BrokenIndirect(0, 0, None)})
    assert value == "<broken-indirect>"


def test_extract_form_fields_from_root_fields():
    page_1 = FakePage("one", marker=1)
    page_2 = FakePage("two", marker=2)
    page_ref = FakeRef(page_2)

    class FakeReader:
        pages = [page_1, page_2]

        @staticmethod
        def get_fields():
            return {
                "txtFirstName": {
                    "/FT": "/Tx",
                    "/V": "Alex",
                    "/Ff": 0x02,
                    "/P": page_ref,
                }
            }

    fields = pdf_reader._extract_form_fields(FakeReader())
    assert len(fields) == 1
    assert fields[0].name == "txtFirstName"
    assert fields[0].field_type == "text"
    assert fields[0].required is True
    assert fields[0].page_number == 2


def test_extract_form_fields_falls_back_to_annotations():
    widget = {
        "/Subtype": "/Widget",
        "/T": "txtEmail",
        "/FT": "/Tx",
        "/V": "test@example.com",
        "/Ff": 0,
    }
    page = FakePage(None, **{"/Annots": [FakeRef(widget)]})

    class FakeReader:
        pages = [page]

        @staticmethod
        def get_fields():
            raise RuntimeError("no root fields")

    fields = pdf_reader._extract_form_fields(FakeReader())
    assert len(fields) == 1
    assert fields[0].name == "txtEmail"
    assert fields[0].value == "test@example.com"
    assert fields[0].page_number == 1


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
