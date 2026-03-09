"""Tests for writer behavior and required-field safeguards."""

from pathlib import Path

import pytest

from pdf_autofiller import pdf_writer as pdf_writer_module
from pdf_autofiller.models import FieldMappingDecision, MappingResult
from pdf_autofiller.pdf_writer import UnresolvedRequiredFieldsError, fill_pdf


def create_minimal_pdf_with_fields(output_path: Path, field_names: list[str]) -> None:
    """
    Create a minimal PDF with form fields for testing.
    
    Note: Keeps PDF structure minimal; tests focus on writer decisions.
    """
    from pypdf import PdfWriter
    from pypdf.generic import NameObject
    
    writer = PdfWriter()
    
    page = writer.add_blank_page(width=612, height=792)

    del field_names  # Placeholder for future explicit field construction.
    if "/Annots" not in page:
        page[NameObject("/Annots")] = []

    with open(output_path, "wb") as f:
        writer.write(f)


@pytest.fixture
def sample_mapping_result():
    """Create sample mapping result for testing."""
    return MappingResult(
        decisions=[
            FieldMappingDecision(
                field_name="txtFirstName",
                semantic_meaning="first_name",
                selected_value="John",
                confidence=0.95,
                reason="Direct match",
                requires_review=False
            ),
            FieldMappingDecision(
                field_name="txtLastName",
                semantic_meaning="last_name",
                selected_value="Doe",
                confidence=0.95,
                reason="Direct match",
                requires_review=False
            ),
        ],
        missing_required=[],
        unmapped_user_keys=[]
    )


@pytest.fixture
def sample_mapping_result_with_review():
    """Create mapping result with a field requiring review."""
    return MappingResult(
        decisions=[
            FieldMappingDecision(
                field_name="txtFirstName",
                semantic_meaning="first_name",
                selected_value="John",
                confidence=0.95,
                reason="Direct match",
                requires_review=False
            ),
            FieldMappingDecision(
                field_name="txtDOB",
                semantic_meaning="date_of_birth",
                selected_value="1990-05-15",
                confidence=0.65,
                reason="Ambiguous date format",
                requires_review=True
            ),
        ],
        missing_required=[],
        unmapped_user_keys=[]
    )


@pytest.fixture
def sample_mapping_result_missing_required():
    """Create mapping result with missing required field."""
    return MappingResult(
        decisions=[
            FieldMappingDecision(
                field_name="txtFirstName",
                semantic_meaning="first_name",
                selected_value="John",
                confidence=0.95,
                reason="Direct match",
                requires_review=False
            ),
        ],
        missing_required=["txtLastName"],
        unmapped_user_keys=[]
    )


def test_fill_pdf_nonexistent_input():
    """Test fill_pdf raises FileNotFoundError for nonexistent input."""
    result = MappingResult(
        decisions=[],
        missing_required=[],
        unmapped_user_keys=[]
    )
    
    with pytest.raises(FileNotFoundError):
        fill_pdf(
            Path("nonexistent.pdf"),
            Path("output.pdf"),
            result
        )


def test_fill_pdf_skips_requires_review_fields(tmp_path, sample_mapping_result_with_review):
    """Review-flagged values are not written and output is still produced."""
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"

    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(input_pdf, "wb") as f:
        writer.write(f)

    fill_pdf(input_pdf, output_pdf, sample_mapping_result_with_review)
    assert output_pdf.exists()


def test_fill_pdf_missing_required_fields(tmp_path, sample_mapping_result_missing_required):
    """Test that fill_pdf raises UnresolvedRequiredFieldsError for missing required fields."""
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(input_pdf, "wb") as f:
        writer.write(f)

    with pytest.raises(UnresolvedRequiredFieldsError) as exc_info:
        fill_pdf(input_pdf, output_pdf, sample_mapping_result_missing_required)
    
    assert "txtLastName" in str(exc_info.value)
    assert "Missing required fields" in str(exc_info.value)


def test_fill_pdf_skips_none_values(tmp_path):
    """Test that fill_pdf skips decisions with None selected_value."""
    result = MappingResult(
        decisions=[
            FieldMappingDecision(
                field_name="txtFirstName",
                semantic_meaning="first_name",
                selected_value=None,
                confidence=0.95,
                reason="Direct match",
                requires_review=False
            ),
            FieldMappingDecision(
                field_name="txtLastName",
                semantic_meaning="last_name",
                selected_value="Doe",
                confidence=0.95,
                reason="Direct match",
                requires_review=False
            ),
        ],
        missing_required=[],
        unmapped_user_keys=[]
    )
    
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(input_pdf, "wb") as f:
        writer.write(f)

    fill_pdf(input_pdf, output_pdf, result)

    assert output_pdf.exists()


def test_unresolved_required_fields_error():
    """Test UnresolvedRequiredFieldsError exception."""
    error = UnresolvedRequiredFieldsError(
        missing_fields=["field1", "field2"],
        skipped_fields=["field3"]
    )
    
    assert "field1" in str(error)
    assert "field2" in str(error)
    assert "field3" in str(error)
    assert "Missing required fields" in str(error)
    assert "Skipped required fields" in str(error)


def test_fill_pdf_creates_output_directory(tmp_path):
    """Test that fill_pdf creates output directory if it doesn't exist."""
    result = MappingResult(
        decisions=[
            FieldMappingDecision(
                field_name="txtFirstName",
                semantic_meaning="first_name",
                selected_value="John",
                confidence=0.95,
                reason="Direct match",
                requires_review=False
            ),
        ],
        missing_required=[],
        unmapped_user_keys=[]
    )
    
    input_pdf = tmp_path / "input.pdf"
    output_dir = tmp_path / "nested" / "output"
    output_pdf = output_dir / "output.pdf"
    
    from pypdf import PdfWriter
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(input_pdf, "wb") as f:
        writer.write(f)

    assert not output_dir.exists()

    fill_pdf(input_pdf, output_pdf, result)

    assert output_dir.exists()
    assert output_pdf.exists()


def test_fill_pdf_raises_when_required_field_is_skipped(tmp_path, monkeypatch):
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    input_pdf.write_bytes(b"%PDF-1.7")

    mapping_result = MappingResult(
        decisions=[
            FieldMappingDecision(
                field_name="txtRequired",
                semantic_meaning="required_field",
                selected_value="value",
                confidence=0.7,
                reason="Ambiguous",
                requires_review=True,
            )
        ],
        missing_required=[],
        unmapped_user_keys=[],
    )

    class FakeReader:
        def __init__(self, _path):
            pass

        @staticmethod
        def get_fields():
            return {"txtRequired": {"/Ff": 0x02}}

    class FakeWriter:
        def __init__(self):
            self.pages = [object()]

        @staticmethod
        def clone_reader_document_root(_reader):
            return None

        @staticmethod
        def update_page_form_field_values(_page, _values):
            return None

        @staticmethod
        def write(output_file):
            output_file.write(b"ok")

    monkeypatch.setattr(pdf_writer_module, "PdfReader", FakeReader)
    monkeypatch.setattr(pdf_writer_module, "PdfWriter", FakeWriter)

    with pytest.raises(UnresolvedRequiredFieldsError) as exc_info:
        fill_pdf(input_pdf, output_pdf, mapping_result)

    assert "txtRequired" in str(exc_info.value)
    assert "Skipped required fields" in str(exc_info.value)


def test_fill_pdf_uses_annotation_fallback_metadata(tmp_path, monkeypatch):
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    input_pdf.write_bytes(b"%PDF-1.7")

    mapping_result = MappingResult(
        decisions=[
            FieldMappingDecision(
                field_name="txtFallback",
                semantic_meaning="fallback_field",
                selected_value="value",
                confidence=0.95,
                reason="Direct match",
                requires_review=False,
            )
        ],
        missing_required=[],
        unmapped_user_keys=[],
    )

    class FakeRef:
        def __init__(self, obj):
            self._obj = obj

        def get_object(self):
            return self._obj

    class FakeReader:
        def __init__(self, _path):
            self.pages = [
                {
                    "/Annots": [
                        FakeRef(
                            {
                                "/Subtype": "/Widget",
                                "/T": "txtFallback",
                                "/Ff": 0,
                            }
                        )
                    ]
                }
            ]

        @staticmethod
        def get_fields():
            raise RuntimeError("no acroform")

    created_writers = []

    class FakeWriter:
        def __init__(self):
            self.pages = [object()]
            self.calls = []
            created_writers.append(self)

        @staticmethod
        def clone_reader_document_root(_reader):
            return None

        def update_page_form_field_values(self, _page, values):
            self.calls.append(values.copy())

        @staticmethod
        def write(output_file):
            output_file.write(b"ok")

    monkeypatch.setattr(pdf_writer_module, "PdfReader", FakeReader)
    monkeypatch.setattr(pdf_writer_module, "PdfWriter", FakeWriter)

    fill_pdf(input_pdf, output_pdf, mapping_result)

    assert output_pdf.exists()
    assert created_writers
    assert created_writers[0].calls == [{"txtFallback": "value"}]
