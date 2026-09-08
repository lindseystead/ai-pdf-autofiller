"""
Run golden corpus cases and report deterministic fill hit rate.

Exit code 1 if any expected field mapping is missing from written fields.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from pdf_autofiller.pipeline import run_fill_pipeline

ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "tests" / "fixtures" / "corpus" / "cases.json"


def load_cases() -> list[dict]:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit(f"Expected a JSON array in {CASES_PATH}")
    return payload


def run_case(case: dict) -> tuple[bool, list[str], list[str]]:
    pdf_path = ROOT / case["pdf"]
    if not pdf_path.is_file():
        return False, [], [f"missing PDF: {pdf_path}"]

    expected: dict[str, str] = case["expected"]
    user_data = case["user_data"]

    with tempfile.TemporaryDirectory(prefix="corpus-") as tmp:
        output = Path(tmp) / "filled.pdf"
        report, _mapping, _count, _pages = run_fill_pipeline(
            pdf_path,
            output,
            user_data,
            strict=True,
            allow_fallback_mapping=False,
            use_semantic_inference=False,
        )

    written = set(report.written_fields)
    expected_fields = list(expected.values())
    hits = [field for field in expected_fields if field in written]
    misses = [field for field in expected_fields if field not in written]
    return not misses, hits, misses


def main() -> int:
    cases = load_cases()
    total_expected = 0
    total_hits = 0
    any_miss = False

    print(f"Corpus report ({len(cases)} cases)")
    print("=" * 60)

    for case in cases:
        name = case.get("name", case.get("pdf", "unnamed"))
        ok, hits, misses = run_case(case)
        expected_n = len(case.get("expected", {}))
        total_expected += expected_n
        total_hits += len(hits)
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}: {len(hits)}/{expected_n} expected fields written")
        if misses:
            any_miss = True
            print(f"       misses: {', '.join(misses)}")

    hit_rate = (total_hits / total_expected * 100.0) if total_expected else 0.0
    print("=" * 60)
    print(f"Hit rate: {total_hits}/{total_expected} ({hit_rate:.1f}%)")
    if any_miss:
        print("Corpus check FAILED")
        return 1
    print("Corpus check PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
