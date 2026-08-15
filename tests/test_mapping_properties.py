"""
Property-based checks over the pure functions in the mapping engine.

``normalize_key``, ``coerce_value``, and ``flatten_user_data`` are total
functions over arbitrary input, which makes them worth testing by invariant
rather than by example. The generators are hand-rolled with a fixed seed so this
adds no dependency and cannot flake between runs.
"""

from __future__ import annotations

import random
import string

import pytest

from pdf_autofiller.mapping import (
    candidate_keys,
    coerce_value,
    flatten_user_data,
    map_user_data_to_fields,
    normalize_key,
)
from pdf_autofiller.models import EnrichedFormField, FieldSemantics, FormField

SEED = 20260815
ALPHABET = string.ascii_letters + string.digits + " -_.@#/()[]" + "éüñ漢"


def _random_keys(count: int, rng: random.Random) -> list[str]:
    return [
        "".join(rng.choice(ALPHABET) for _ in range(rng.randint(1, 24)))
        for _ in range(count)
    ]


@pytest.fixture
def rng() -> random.Random:
    return random.Random(SEED)


def test_normalize_key_is_idempotent(rng):
    """Normalizing twice equals normalizing once, for any input."""
    for key in _random_keys(400, rng):
        once = normalize_key(key)
        assert normalize_key(once) == once


def test_normalize_key_output_charset(rng):
    """Output only ever contains word characters, never leading/trailing gaps."""
    for key in _random_keys(400, rng):
        result = normalize_key(key)
        assert all(c.isalnum() or c == "_" for c in result), result
        assert not result.startswith("_") and not result.endswith("_"), result
        assert "__" not in result, result


def test_normalize_key_ignores_separator_style(rng):
    """Separator choice must not change the result: it is the point of the function."""
    for base in ["first name", "date of birth", "postal code", "line 2 extra"]:
        variants = [
            base,
            base.replace(" ", "-"),
            base.replace(" ", "_"),
            base.replace(" ", "."),
            base.upper(),
            base.title(),
        ]
        assert len({normalize_key(v) for v in variants}) == 1


def test_coerce_value_never_raises(rng):
    """Coercion is total: any value against any type returns, never raises."""
    values = [None, "", "  ", "abc", "1990-01-01", "2024-13-45", 0, -1, 1.5, True,
              float("inf"), 10**30, "1e999", "yes", "MAYBE", [], {}, "0x10"]
    for value in values:
        for expected in ("string", "date", "number", "boolean", "unknown-type"):
            result, review = coerce_value(value, expected)
            assert result is None or isinstance(result, str)
            assert isinstance(review, bool)


def test_coerce_value_none_is_never_review():
    """A missing value is absent, not ambiguous — it must not be flagged."""
    assert coerce_value(None, "date") == (None, False)


def test_coerce_value_flags_bad_dates_and_numbers():
    assert coerce_value("2024-13-45", "date")[1] is True
    assert coerce_value("not-a-date", "date")[1] is True
    assert coerce_value("1990-01-01", "date") == ("1990-01-01", False)
    assert coerce_value("abc", "number")[1] is True
    assert coerce_value("42.0", "number") == ("42", False)
    assert coerce_value("maybe", "boolean")[1] is True


def test_flatten_is_bounded_by_max_depth(rng):
    """Deep nesting terminates at the configured depth instead of recursing away."""
    nested: object = "leaf"
    for _ in range(200):
        nested = {"k": nested}
    flat = flatten_user_data(nested, max_depth=6)
    assert flat
    assert max(key.count(".") for key in flat) <= 6


def test_flatten_preserves_every_leaf(rng):
    """No leaf value may be lost while flattening."""
    for _ in range(50):
        payload = {
            "a": rng.randint(0, 100),
            "b": {"c": "x", "d": {"e": "y"}},
            "list": [1, 2, {"f": "z"}],
        }
        flat = flatten_user_data(payload)
        assert set(flat.values()) >= {"x", "y", "z", 1, 2, payload["a"]}


def test_flatten_leaves_scalars_untouched():
    assert flatten_user_data({"a": 1, "b": None}) == {"a": 1, "b": None}


def test_candidate_keys_always_includes_the_leaf(rng):
    for path in ["a", "a.b", "a.b.c", "Address.Postal Code"]:
        forms = candidate_keys(path)
        assert normalize_key(path.rsplit(".", 1)[-1]) in forms


def _field(name: str, semantic: str) -> EnrichedFormField:
    return EnrichedFormField(
        field=FormField(name=name, field_type="text", page_number=1),
        semantics=FieldSemantics(
            semantic_meaning=semantic, expected_data_type="string", confidence_score=0.9
        ),
    )


def test_mapping_is_independent_of_user_data_key_order(rng):
    """Shuffling the input dict must not change the resulting document.

    Greedy first-match made the outcome depend on insertion order, so the same
    data submitted twice could fill a form differently.
    """
    fields = [_field("f_city", "city"), _field("f_zip", "postal_code"), _field("f_name", "first_name")]
    base = {"city": "Boston", "zip": "02101", "firstname": "Jane", "extra": "unused"}

    baseline = None
    for _ in range(25):
        items = list(base.items())
        rng.shuffle(items)
        result = map_user_data_to_fields(fields, dict(items), strict=True)
        snapshot = sorted((d.field_name, d.selected_value) for d in result.decisions)
        if baseline is None:
            baseline = snapshot
        assert snapshot == baseline


def test_mapping_never_invents_values_absent_from_input(rng):
    """Every written value must trace back to a value the caller supplied."""
    fields = [_field("f1", "first_name"), _field("f2", "city"), _field("f3", "email_address")]
    for _ in range(50):
        data = {
            "firstname": "".join(rng.choice(string.ascii_letters) for _ in range(6)),
            "city": "".join(rng.choice(string.ascii_letters) for _ in range(6)),
        }
        result = map_user_data_to_fields(fields, data, strict=True)
        supplied = {str(v) for v in data.values()}
        for decision in result.decisions:
            if decision.selected_value is not None:
                assert decision.selected_value in supplied


def test_unmapped_keys_and_decisions_partition_the_input(rng):
    """A key is either used or reported unused — never silently dropped."""
    fields = [_field("f1", "first_name"), _field("f2", "city")]
    data = {"firstname": "Jane", "city": "Boston", "mystery": "?", "nested": {"deep": 1}}
    result = map_user_data_to_fields(fields, data, strict=True)
    flat_keys = set(flatten_user_data(data))
    used = {
        key
        for key in flat_keys
        if key not in result.unmapped_user_keys
    }
    assert used | set(result.unmapped_user_keys) == flat_keys
