"""Reproducible, value-free reporting for AcroForm compatibility manifests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .pipeline import run_fill_pipeline


def load_compatibility_cases(manifest: str | Path) -> list[dict[str, Any]]:
    path = Path(manifest)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not payload:
        raise ValueError("compatibility manifest must be a non-empty JSON array")
    for index, case in enumerate(payload):
        if not isinstance(case, dict):
            raise ValueError(f"compatibility case {index} must be an object")
        for required in ("name", "pdf", "user_data", "expected"):
            if required not in case:
                raise ValueError(f"compatibility case {index} is missing {required!r}")
        if not isinstance(case["user_data"], dict) or not isinstance(case["expected"], dict):
            raise ValueError(f"compatibility case {index} user_data and expected must be objects")
    return payload


def run_compatibility_manifest(
    manifest: str | Path,
    *,
    repo_root: str | Path,
    output_dir: str | Path,
) -> dict[str, Any]:
    """Run every available case and return a report that contains no input values."""
    root = Path(repo_root)
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    expected_total = 0
    hit_total = 0

    for case in load_compatibility_cases(manifest):
        name = str(case["name"])
        pdf = root / str(case["pdf"])
        expected_fields = set(str(value) for value in case["expected"].values())
        if not pdf.is_file():
            results.append(
                {
                    "name": name,
                    "status": "skipped",
                    "reason": "PDF is not available locally",
                    "expected_fields": len(expected_fields),
                    "matched_fields": 0,
                }
            )
            continue
        expected_total += len(expected_fields)

        output = destination / f"{name}.pdf"
        try:
            report, mapping, field_count, pages = run_fill_pipeline(
                pdf,
                output,
                case["user_data"],
                strict=True,
                allow_fallback_mapping=False,
                use_semantic_inference=False,
            )
            written = set(report.written_fields)
            matched = len(expected_fields & written)
            hit_total += matched
            PdfReader(output).get_fields()  # output must remain parseable as an AcroForm
            missing_expected = sorted(expected_fields - written)
            results.append(
                {
                    "name": name,
                    "status": "passed" if not missing_expected else "failed",
                    "pages": pages,
                    "fields_total": field_count,
                    "expected_fields": len(expected_fields),
                    "matched_fields": matched,
                    "missing_expected_fields": missing_expected,
                    "missing_required_count": len(mapping.missing_required),
                    "display_warning_count": len(report.display_warnings),
                }
            )
        except Exception as exc:
            results.append(
                {
                    "name": name,
                    "status": "failed",
                    "reason": type(exc).__name__,
                    "expected_fields": len(expected_fields),
                    "matched_fields": 0,
                }
            )

    executed = [result for result in results if result["status"] != "skipped"]
    return {
        "cases_total": len(results),
        "cases_executed": len(executed),
        "cases_passed": sum(result["status"] == "passed" for result in executed),
        "cases_failed": sum(result["status"] == "failed" for result in executed),
        "cases_skipped": sum(result["status"] == "skipped" for result in results),
        "mapping_hit_rate": hit_total / expected_total if expected_total else 0.0,
        "results": results,
    }
