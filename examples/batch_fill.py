"""Fill the sample form once per person in examples/contractors.json.

Run from a clone of the repository:

    python examples/batch_fill.py                 # writes out/contractors/
    python examples/batch_fill.py /tmp/contractors
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pdf_autofiller import fill_batch

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PDF = REPO_ROOT / "samples" / "sample_form.pdf"
RECORDS = REPO_ROOT / "examples" / "contractors.json"


def main(argv: list[str]) -> int:
    output_dir = Path(argv[1]) if len(argv) > 1 else Path("out") / "contractors"
    records = json.loads(RECORDS.read_text(encoding="utf-8"))
    report = fill_batch(SAMPLE_PDF, records, output_dir, filename_key="lastname")
    print(f"Wrote {report.written} PDF(s) to {output_dir}")
    for item in report.items:
        if item.error:
            print(f"  record {item.index}: {item.error}")
        else:
            print(f"  {item.output}: {', '.join(item.written_fields)}")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
