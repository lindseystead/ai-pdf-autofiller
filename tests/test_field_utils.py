"""Tests for shared PDF field helpers."""

from pdf_autofiller.field_utils import (
    is_field_required,
    is_opaque_field_name,
    opaque_mapping_hints,
)


class _FakeField:
    def __init__(self, ff: int):
        self._ff = ff

    def get(self, key, default=0):
        if key == "/Ff":
            return self._ff
        return default


def test_is_field_required_when_flag_set():
    assert is_field_required(_FakeField(0x02)) is True


def test_is_field_required_when_flag_clear():
    assert is_field_required(_FakeField(0x00)) is False


def test_is_field_required_when_object_missing():
    assert is_field_required(None) is False


def test_opaque_field_name_detection():
    assert is_opaque_field_name("field_12") is True
    assert is_opaque_field_name("Text1") is True
    assert is_opaque_field_name("a1b2c3d4e5f6478899aabbccddeeff00") is True
    assert is_opaque_field_name("550e8400-e29b-41d4-a716-446655440000") is True
    assert is_opaque_field_name("txtFirstName") is False
    assert is_opaque_field_name("EmployeeFirstName_AF_text") is False


def test_opaque_mapping_hints_for_unmatched():
    hints = opaque_mapping_hints(
        ["field_12", "txtFirstName"],
        unmatched_opaque=["field_12"],
        use_semantic_inference=False,
    )
    assert hints
    assert any("opaque" in hint.lower() for hint in hints)
    assert any("semantic inference" in hint.lower() for hint in hints)
