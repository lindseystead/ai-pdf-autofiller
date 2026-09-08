"""Library surface tests: inspect / preview / fill_detailed / AliasRegistry."""

from pathlib import Path

import pytest

from pdf_autofiller import fill_detailed, inspect, preview
from pdf_autofiller.aliases import AliasRegistry, set_default_registry

SAMPLE = Path("samples/sample_form.pdf")


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample PDF not present")
def test_inspect_lists_fields():
    result = inspect(SAMPLE)
    assert result.pages >= 1
    assert result.field_count >= 3
    names = {field.name for field in result.fields}
    assert "txtFirstName" in names


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample PDF not present")
def test_preview_returns_mapping_without_writing(tmp_path: Path):
    result = preview(
        SAMPLE,
        {"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01", "unused": "x"},
        strict=True,
    )
    assert result.field_count >= 3
    assert not (tmp_path / "should_not_exist.pdf").exists()
    names = {d.field_name for d in result.mapping.decisions}
    assert "txtFirstName" in names
    assert "unused" in result.mapping.unmapped_user_keys


@pytest.mark.skipif(not SAMPLE.exists(), reason="sample PDF not present")
def test_fill_detailed_includes_report_and_mapping(tmp_path: Path):
    outcome = fill_detailed(
        SAMPLE,
        {"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01"},
        tmp_path / "out.pdf",
        strict=True,
    )
    assert outcome.pages is not None and outcome.pages >= 1
    assert "txtFirstName" in outcome.report.written_fields
    assert outcome.field_count >= 3


def test_alias_registry_load_isolated_from_packs(tmp_path: Path):
    pack = tmp_path / "custom.json"
    pack.write_text('{"widget_sku": ["sku", "product_sku"]}', encoding="utf-8")
    registry = AliasRegistry.load(pack_dir=tmp_path, include_builtin=True)
    assert registry.canonicalize("sku") == "widget_sku"
    assert "first_name" in registry.aliases

    empty = AliasRegistry.load(pack_dir=tmp_path, include_builtin=False)
    assert "first_name" not in empty.aliases
    assert empty.canonicalize("sku") == "widget_sku"


def test_set_default_registry_reload(tmp_path: Path):
    pack = tmp_path / "only.json"
    pack.write_text('{"fleet_id": ["vin", "vehicle_id"]}', encoding="utf-8")
    previous = AliasRegistry.load()
    try:
        set_default_registry(AliasRegistry.load(pack_dir=tmp_path, include_builtin=False))
        from pdf_autofiller.mapping import canonicalize_semantic

        assert canonicalize_semantic("vin") == "fleet_id"
    finally:
        set_default_registry(previous)
