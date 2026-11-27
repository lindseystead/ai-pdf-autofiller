"""Compatibility reports are reproducible and never echo input values."""

import json
from pathlib import Path

import pytest

from pdf_autofiller.compatibility import load_compatibility_cases, run_compatibility_manifest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "tests" / "fixtures" / "corpus" / "cases.json"


def test_public_compatibility_manifest_passes_without_leaking_values(tmp_path):
    report = run_compatibility_manifest(MANIFEST, repo_root=ROOT, output_dir=tmp_path)
    serialized = json.dumps(report)

    assert report["cases_executed"] == 6
    assert report["cases_failed"] == 0
    assert report["mapping_hit_rate"] == 1.0
    assert "Jane Doe" not in serialized
    assert "123-45-6789" not in serialized


def test_missing_private_pdf_is_reported_as_skipped(tmp_path):
    manifest = tmp_path / "private.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "name": "private-form",
                    "pdf": "tests/fixtures/compatibility/private/form.pdf",
                    "user_data": {"name": "Sensitive Person"},
                    "expected": {"name": "person_name"},
                }
            ]
        ),
        encoding="utf-8",
    )
    report = run_compatibility_manifest(manifest, repo_root=ROOT, output_dir=tmp_path / "out")
    assert report["cases_skipped"] == 1
    assert "Sensitive Person" not in json.dumps(report)


def test_invalid_manifest_fails_clearly(tmp_path):
    manifest = tmp_path / "invalid.json"
    manifest.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="non-empty JSON array"):
        load_compatibility_cases(manifest)
