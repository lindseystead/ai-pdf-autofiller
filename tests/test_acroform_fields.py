"""Tests for shared AcroForm field extraction helpers."""

from pypdf.generic import IndirectObject

from pdf_autofiller import acroform_fields


class FakeRef:
    def __init__(self, obj):
        self._obj = obj

    def get_object(self):
        return self._obj


class FakePage(dict):
    pass


def test_collect_field_objects_from_root_fields():
    class FakeReader:
        @staticmethod
        def get_fields():
            return {"txtName": {"/FT": "/Tx", "/V": "Ada"}}

        pages = []

    collected = acroform_fields.collect_field_objects(FakeReader())
    assert "txtName" in collected


def test_collect_field_objects_falls_back_to_widgets():
    widget = {
        "/Subtype": "/Widget",
        "/T": "txtEmail",
        "/FT": "/Tx",
    }
    page = FakePage(**{"/Annots": [FakeRef(widget)]})

    class FakeReader:
        pages = [page]

        @staticmethod
        def get_fields():
            raise RuntimeError("no root fields")

    collected = acroform_fields.collect_field_objects(FakeReader())
    assert collected["txtEmail"] is widget


def test_find_field_page_defaults_when_unresolvable():
    class FakeReader:
        pages = [FakePage()]

    page_num = acroform_fields.find_field_page(FakeReader(), {"/P": object()})
    assert page_num == 1


def test_get_field_value_returns_none_for_missing():
    assert acroform_fields.get_field_value({}) is None


def test_get_field_type_unknown():
    assert acroform_fields.get_field_type({}) == "unknown"


def test_get_field_type_variants():
    assert acroform_fields.get_field_type({"/FT": "/Tx"}) == "text"
    assert acroform_fields.get_field_type({"/FT": "/Btn"}) == "button"
    assert acroform_fields.get_field_type({"/FT": "/Ch"}) == "choice"
    assert acroform_fields.get_field_type({"/FT": "/Sig"}) == "signature"
    assert acroform_fields.get_field_type({"/FT": "/Other"}) == "unknown"


def test_get_field_value_handles_direct_values():
    assert acroform_fields.get_field_value({"/V": "hello"}) == "hello"
    assert acroform_fields.get_field_value({"/V": 123}) == "123"
    assert acroform_fields.get_field_value({"/V": True}) == "True"
    assert acroform_fields.get_field_value({"/V": None}) is None


def test_get_field_value_handles_reference_resolution(monkeypatch):
    class FakeIndirect(IndirectObject):
        def __init__(self, value):
            self._value = value

        def get_object(self):
            return self._value

    assert acroform_fields.get_field_value({"/V": FakeIndirect("resolved")}) == "resolved"

    class BrokenIndirect(IndirectObject):
        def get_object(self):
            raise RuntimeError("broken")

        def __str__(self):
            return "<broken-indirect>"

    value = acroform_fields.get_field_value({"/V": BrokenIndirect(0, 0, None)})
    assert value == "<broken-indirect>"


def test_extract_form_fields_from_root_fields():
    page_1 = FakePage(marker=1)
    page_2 = FakePage(marker=2)
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

    fields = acroform_fields.extract_form_fields(FakeReader())
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
    page = FakePage(**{"/Annots": [FakeRef(widget)]})

    class FakeReader:
        pages = [page]

        @staticmethod
        def get_fields():
            raise RuntimeError("no root fields")

    fields = acroform_fields.extract_form_fields(FakeReader())
    assert len(fields) == 1
    assert fields[0].name == "txtEmail"
    assert fields[0].value == "test@example.com"
    assert fields[0].page_number == 1
