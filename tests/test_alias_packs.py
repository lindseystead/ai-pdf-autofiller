"""
Every shipped alias pack must load, and none may weaken the built-ins.

Packs are data, so they carry no tests of their own — a typo, a duplicated
semantic, or a variant that collides with another pack would otherwise reach
users silently. Adding a pack should be safe; these tests are what make it safe.
"""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from pdf_autofiller.mapping import (
    BUILTIN_FIELD_ALIASES,
    build_field_aliases,
    find_deterministic_match,
    normalize_key,
    reload_field_aliases,
)

PACK_DIR = Path(__file__).resolve().parents[1] / "src" / "pdf_autofiller" / "form_aliases"


def _packs() -> dict[str, dict[str, list[str]]]:
    return {
        path.name: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(PACK_DIR.glob("*.json"))
    }


@pytest.fixture(autouse=True)
def _fresh_aliases():
    reload_field_aliases()
    yield
    reload_field_aliases()


def test_packs_are_shipped():
    assert _packs(), "no alias packs found — the path is wrong, or they stopped shipping"


@pytest.mark.parametrize("name", sorted(p.name for p in PACK_DIR.glob("*.json")))
def test_pack_is_well_formed(name):
    """A malformed pack is skipped at load time, which fails silently for users."""
    payload = json.loads((PACK_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(payload, dict), f"{name}: top level must be an object"

    for semantic, variants in payload.items():
        assert isinstance(semantic, str) and semantic, f"{name}: bad semantic key"
        assert semantic == normalize_key(semantic), (
            f"{name}: semantic {semantic!r} is not already normalized, so it can never match"
        )
        assert isinstance(variants, list) and variants, f"{name}: {semantic} has no variants"
        assert all(isinstance(v, str) and v for v in variants), f"{name}: {semantic} has a bad variant"
        normalized = [normalize_key(v) for v in variants]
        assert len(set(normalized)) == len(normalized), (
            f"{name}: {semantic} has variants that normalize to the same key"
        )
        assert semantic not in normalized, (
            f"{name}: {semantic} lists itself as a variant, which is redundant"
        )


def test_packs_never_weaken_the_builtins():
    """The bug this guards: dict.update replacing an alias list instead of extending it."""
    merged = build_field_aliases()
    for semantic, builtin_variants in BUILTIN_FIELD_ALIASES.items():
        missing = set(builtin_variants) - set(merged.get(semantic, []))
        assert not missing, (
            f"alias packs dropped built-in variants for {semantic}: {sorted(missing)}"
        )


def test_builtin_aliases_still_match_after_packs_load():
    """End-to-end version of the above, through the matcher users actually hit."""
    for probe, semantic in [
        ("fname", "first_name"),
        ("surname", "last_name"),
        ("dob", "date_of_birth"),
        ("zip", "postal_code"),
    ]:
        matched, _, _, _, _ = find_deterministic_match(semantic, {probe: "x"}, "string")
        assert matched == probe, f"{probe} no longer matches {semantic}"


@pytest.mark.parametrize("name", sorted(p.name for p in PACK_DIR.glob("*.json")))
def test_no_variant_is_claimed_twice_within_one_pack(name):
    """Inside one pack an ambiguous variant is a genuine authoring mistake.

    Across packs it is not: matching is keyed by the *field's* semantic, so the
    same word legitimately fills different kinds of field on different forms —
    `legal_name` fills a `full_name` field on one form and a `taxpayer_name`
    field on a W-9. That is covered by the test below.
    """
    payload = json.loads((PACK_DIR / name).read_text(encoding="utf-8"))
    owners: dict[str, set[str]] = defaultdict(set)
    for semantic, variants in payload.items():
        for variant in variants:
            owners[normalize_key(variant)].add(semantic)

    contested = {v: sorted(s) for v, s in owners.items() if len(s) > 1}
    assert not contested, f"{name}: variants claimed by two semantics in one pack: {contested}"


def test_a_variant_may_serve_several_semantics_across_forms():
    """Cross-form synonyms are intentional, and this pins that behaviour down.

    Different forms name the same human concept differently. Matching looks up
    aliases by the field's semantic, so one user key filling either kind of
    field is correct, not a collision.
    """
    for semantic in ("full_name", "taxpayer_name"):
        matched, _, _, _, _ = find_deterministic_match(semantic, {"legal_name": "Jane"}, "string")
        assert matched == "legal_name", f"legal_name should fill a {semantic} field"


def test_packs_do_not_fragment_a_builtin_concept():
    """A pack must not invent a second semantic for something built-ins own.

    A pack semantic whose variants are a subset of a built-in semantic's variants
    is the same concept under a new name; which one wins would then depend on a
    form's field naming rather than on meaning.
    """
    builtin_by_variant = {
        normalize_key(v): semantic
        for semantic, variants in BUILTIN_FIELD_ALIASES.items()
        for v in variants
    }
    duplicates = []
    for name, payload in _packs().items():
        for semantic, variants in payload.items():
            if semantic in BUILTIN_FIELD_ALIASES:
                continue
            owners = {builtin_by_variant.get(normalize_key(v)) for v in variants}
            owners.discard(None)
            if len(owners) == 1 and all(
                normalize_key(v) in builtin_by_variant for v in variants
            ):
                duplicates.append(f"{name}:{semantic} duplicates built-in {owners.pop()}")
    assert not duplicates, f"packs re-declare built-in concepts: {duplicates}"


def test_pack_semantics_do_not_shadow_a_builtin_variant():
    """A pack semantic that equals a built-in variant would fight the built-in."""
    builtin_variants = {
        normalize_key(v) for variants in BUILTIN_FIELD_ALIASES.values() for v in variants
    }
    for name, payload in _packs().items():
        clashing = {s for s in payload if normalize_key(s) in builtin_variants}
        assert not clashing, f"{name}: semantics shadow a built-in variant: {sorted(clashing)}"


@pytest.mark.parametrize(
    "semantic,variant",
    [
        ("alien_registration_number", "uscis_number"),
        ("form_i94_admission_number", "i94_number"),
        ("exempt_from_withholding", "claim_exempt"),
        ("extra_withholding", "additional_withholding"),
        ("taxpayer_name", "legal_name"),
        ("emergency_contact_name", "emergency_contact"),
    ],
)
def test_shipped_packs_resolve_their_own_aliases(semantic, variant):
    matched, _, _, _, _ = find_deterministic_match(semantic, {variant: "x"}, "string")
    assert matched == variant, f"{variant} does not resolve to {semantic}"
