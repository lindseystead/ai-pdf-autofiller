"""Golden corpus hit-rate tests for deterministic AcroForm fills."""

import json
from pathlib import Path

import pytest

from pdf_autofiller.pipeline import run_fill_pipeline

ROOT = Path(__file__).resolve().parent
CASES_PATH = ROOT / "fixtures" / "corpus" / "cases.json"


def _load_cases() -> list[dict]:
    return json.loads(CASES_PATH.read_text(encoding="utf-8"))


@pytest.mark.parametrize("case", _load_cases(), ids=lambda c: c["name"])
def test_corpus_case_writes_expected_fields(case: dict, tmp_path: Path):
    pdf_path = ROOT.parent / case["pdf"]
    if not pdf_path.is_file():
        pytest.skip(f"corpus PDF missing: {pdf_path}")

    report, mapping_result, _count, _pages = run_fill_pipeline(
        pdf_path,
        tmp_path / "filled.pdf",
        case["user_data"],
        strict=True,
        allow_fallback_mapping=False,
        use_semantic_inference=False,
    )

    written = set(report.written_fields)
    for user_key, field_name in case["expected"].items():
        assert field_name in written, (
            f"{case['name']}: expected {user_key} → {field_name} to be written; "
            f"got {sorted(written)}; missing_required={mapping_result.missing_required}"
        )
