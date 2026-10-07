"""Fill the bundled sample form from a JSON-style dict.

Run from a clone of the repository:

    python examples/quickstart.py            # writes out/filled_sample.pdf
    python examples/quickstart.py my.pdf     # custom output path
"""

from __future__ import annotations

import sys
from pathlib import Path

from pdf_autofiller import fill

REPO_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PDF = REPO_ROOT / "samples" / "sample_form.pdf"


def main(argv: list[str]) -> int:
    output = Path(argv[1]) if len(argv) > 1 else Path("out") / "filled_sample.pdf"
    output.parent.mkdir(parents=True, exist_ok=True)

    # Keys don't need to match the form's widget names (txtFirstName, txtDOB, ...):
    # common synonyms are matched by alias. Strict mode (the default) refuses to
    # write if a required field can't be resolved; pass allow_partial=True to
    # write anyway and inspect report.missing_required_fields.
    report = fill(
        SAMPLE_PDF,
        {"firstname": "Jane", "lastname": "Doe", "dob": "1990-01-01"},
        output,
    )

    print(f"Wrote {output}")
    print(f"  filled:   {', '.join(report.written_fields)}")
    print(f"  unfilled: {', '.join(report.unfilled_fields) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
