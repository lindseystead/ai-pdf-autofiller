#!/usr/bin/env python3
"""Generate a shareable terminal demo transcript for README and launch posts."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "assets" / "demo-terminal.txt"


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        "$ git clone https://github.com/lindseystead/ai-pdf-autofiller.git",
        "$ cd ai-pdf-autofiller && make run-api",
        "INFO:     Uvicorn running on http://0.0.0.0:8000",
        "",
        "$ open http://localhost:8000/playground",
        "# Upload samples/sample_form.pdf, paste JSON, click Fill PDF",
        "",
        "$ curl -s -X POST http://localhost:8000/fill \\",
        '  -F "pdf_file=@samples/sample_form.pdf;type=application/pdf" \\',
        f"  -F 'user_data={json.dumps({'firstname': 'Jane', 'lastname': 'Doe', 'dob': '1990-01-01'})}' \\",
        '  -F "strict=true" \\',
        "  -o filled.pdf",
        "$ ls -lh filled.pdf",
        "-rw-r--r--  1 dev  staff   12K filled.pdf",
        "",
        "$ python -c \"from pdf_autofiller import fill; fill('samples/sample_form.pdf', {'firstname':'Jane'}, 'sdk-filled.pdf')\"",
        "SDK filled.pdf written.",
    ]

    # Optionally run the real demo workflow for authenticity.
    try:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.demo_workflow", str(ROOT / "samples" / "sample_form.pdf")],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env={"PYTHONPATH": str(ROOT / "src"), **dict(**__import__("os").environ)},
            check=False,
            timeout=30,
        )
        if result.stdout.strip():
            lines.extend(["", "# Live demo_workflow output:", result.stdout.strip()])
    except (subprocess.SubprocessError, OSError):
        pass

    OUTPUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
