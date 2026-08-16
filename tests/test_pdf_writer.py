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


def create_pdf_with_checkbox(output_path: Path, field_name: str = "chkAgree") -> None:
    """Create a minimal PDF containing a single checkbox with /Yes and /Off states."""
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject,
        DictionaryObject,
        NameObject,
        NumberObject,
        TextStringObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)

    normal = DictionaryObject(
        {NameObject("/Yes"): DictionaryObject(), NameObject("/Off"): DictionaryObject()}
    )
    appearance = DictionaryObject({NameObject("/N"): normal})

    checkbox = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject("/Btn"),
            NameObject("/T"): TextStringObject(field_name),
            NameObject("/Rect"): ArrayObject(
                [NumberObject(10), NumberObject(10), NumberObject(30), NumberObject(30)]
            ),
            NameObject("/AP"): appearance,
            NameObject("/AS"): NameObject("/Off"),
            NameObject("/V"): NameObject("/Off"),
        }
    )
    checkbox_ref = writer._add_object(checkbox)
    page[NameObject("/Annots")] = ArrayObject([checkbox_ref])
    acro_form = DictionaryObject({NameObject("/Fields"): ArrayObject([checkbox_ref])})
    writer._root_object[NameObject("/AcroForm")] = acro_form

    with open(output_path, "wb") as handle:
        writer.write(handle)


def _checkbox_decision(value: str, field_name: str = "chkAgree") -> MappingResult:
    return MappingResult(
        decisions=[
            FieldMappingDecision(
                field_name=field_name,
                semantic_meaning="agree_to_terms",
                selected_value=value,
                confidence=0.95,
                reason="Direct match",
                requires_review=False,
            )
        ],
        missing_required=[],
        unmapped_user_keys=[],
    )


@pytest.mark.parametrize("value", ["true", "Yes", "1", "on", "/Yes"])
def test_fill_pdf_checks_checkbox_for_truthy_values(tmp_path, value):
    """Truthy values must set the checkbox to its on-state, not leave it /Off."""
    from pypdf import PdfReader

    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    create_pdf_with_checkbox(input_pdf)

    fill_pdf(input_pdf, output_pdf, _checkbox_decision(value))

    fields = PdfReader(str(output_pdf)).get_fields()
    assert str(fields["chkAgree"].get("/V")) == "/Yes"


@pytest.mark.parametrize("value", ["false", "No", "0", "off"])
def test_fill_pdf_unchecks_checkbox_for_falsy_values(tmp_path, value):
    """Falsy values must resolve to the /Off state."""
    from pypdf import PdfReader

    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    create_pdf_with_checkbox(input_pdf)

    fill_pdf(input_pdf, output_pdf, _checkbox_decision(value))

    fields = PdfReader(str(output_pdf)).get_fields()
    assert str(fields["chkAgree"].get("/V")) == "/Off"


def test_fill_pdf_returns_report_listing_review_skips(tmp_path, sample_mapping_result_with_review):
    """Non-required review-flagged fields are reported, not silently dropped."""
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"

    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with open(input_pdf, "wb") as f:
        writer.write(f)

    report = fill_pdf(input_pdf, output_pdf, sample_mapping_result_with_review)

    assert "txtDOB" in report.skipped_review_fields
    assert "txtDOB" not in report.written_fields


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


def _text_decision(field_name: str, value: str) -> MappingResult:
    return MappingResult(
        decisions=[
            FieldMappingDecision(
                field_name=field_name,
                semantic_meaning="agree_to_terms",
                selected_value=value,
                confidence=0.95,
                reason="Direct match",
                requires_review=False,
            )
        ],
        missing_required=[],
        unmapped_user_keys=[],
    )


def test_written_fields_are_verified_against_the_output(tmp_path):
    """A reported write must be present in the document, not merely attempted."""
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    create_pdf_with_checkbox(input_pdf)

    report = fill_pdf(input_pdf, output_pdf, _text_decision("chkAgree", "true"))

    assert report.written_fields == ["chkAgree"]
    assert report.failed_fields == []


def test_silently_dropped_write_is_reported_as_failed(tmp_path, monkeypatch):
    """pypdf can decline a write without raising; that must not read as success.

    Previously the field was recorded as written before the write was attempted,
    so a swallowed failure produced an incomplete PDF that reported as complete.
    """
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    create_pdf_with_checkbox(input_pdf)

    def silently_do_nothing(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        pdf_writer_module.PdfWriter,
        "update_page_form_field_values",
        silently_do_nothing,
    )

    report = fill_pdf(input_pdf, output_pdf, _text_decision("chkAgree", "true"))

    assert report.written_fields == []
    assert report.failed_fields == ["chkAgree"]


def test_unverifiable_required_field_raises(tmp_path, monkeypatch):
    """An unverifiable required field means the document is not complete."""
    from pypdf.generic import NameObject, NumberObject

    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    create_pdf_with_checkbox(input_pdf, field_name="chkRequired")

    real_collect = pdf_writer_module.collect_field_objects

    def collect_marking_required(reader):
        fields = real_collect(reader)
        for field_obj in fields.values():
            if hasattr(field_obj, "__setitem__"):
                field_obj[NameObject("/Ff")] = NumberObject(2)
        return fields

    monkeypatch.setattr(pdf_writer_module, "collect_field_objects", collect_marking_required)
    monkeypatch.setattr(
        pdf_writer_module.PdfWriter,
        "update_page_form_field_values",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(UnresolvedRequiredFieldsError) as excinfo:
        fill_pdf(input_pdf, output_pdf, _text_decision("chkRequired", "true"))

    assert "chkRequired" in excinfo.value.missing_fields


def test_verification_fails_closed_when_output_cannot_be_introspected(
    tmp_path, monkeypatch
):
    """If the output cannot be introspected, nothing may be claimed as verified.

    Failing open here would let `written_fields` assert a confirmation the
    service never obtained — the exact thing verification exists to prevent.
    """
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    create_pdf_with_checkbox(input_pdf)

    calls = {"count": 0}
    real_collect = pdf_writer_module.collect_field_objects

    def collect_then_blank(reader):
        calls["count"] += 1
        # First call inspects the input; later calls verify the output.
        return real_collect(reader) if calls["count"] == 1 else {}

    monkeypatch.setattr(pdf_writer_module, "collect_field_objects", collect_then_blank)

    report = fill_pdf(input_pdf, output_pdf, _text_decision("chkAgree", "true"))

    assert report.written_fields == []
    assert report.failed_fields == ["chkAgree"]


def test_verification_fails_closed_when_output_cannot_be_read(tmp_path, monkeypatch):
    """An unreadable output document is unverified, not verified."""
    input_pdf = tmp_path / "input.pdf"
    output_pdf = tmp_path / "output.pdf"
    create_pdf_with_checkbox(input_pdf)

    real_reader = pdf_writer_module.PdfReader
    state = {"first": True}

    def reader_failing_on_output(path):
        if state["first"]:
            state["first"] = False
            return real_reader(path)
        raise OSError("output unreadable")

    monkeypatch.setattr(pdf_writer_module, "PdfReader", reader_failing_on_output)

    report = fill_pdf(input_pdf, output_pdf, _text_decision("chkAgree", "true"))

    assert report.written_fields == []
    assert report.failed_fields == ["chkAgree"]
