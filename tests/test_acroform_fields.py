"""Tests for shared AcroForm field extraction helpers."""

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
