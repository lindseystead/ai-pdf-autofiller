"""Generate a value-free compatibility report from public and private manifests."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pdf_autofiller.compatibility import run_compatibility_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path("tests/fixtures/corpus/cases.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("compatibility-output"))
    parser.add_argument("--report", type=Path, default=Path("compatibility-report.json"))
    parser.add_argument("--fail-under", type=float, default=0.95)
    args = parser.parse_args()

    report = run_compatibility_manifest(
        args.manifest,
        repo_root=Path.cwd(),
        output_dir=args.output_dir,
    )
    args.report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return int(report["cases_failed"] > 0 or report["mapping_hit_rate"] < args.fail_under)


if __name__ == "__main__":
    raise SystemExit(main())
