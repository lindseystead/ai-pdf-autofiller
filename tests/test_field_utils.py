"""Tests for shared PDF field helpers."""

from pdf_autofiller.field_utils import is_field_required


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
