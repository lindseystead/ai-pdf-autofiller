"""
A ceiling on function complexity, so the hot spots do not grow back.

`fill_pdf` reached a cyclomatic complexity of 34 by accretion — no single
change made it unreadable, and nothing failed when it got worse. This test is
the thing that would have failed.

The budget is a ceiling, not a target: C-grade (11-20) is fine for genuinely
branchy work like walking a malformed PDF. What is banned is D and above, which
is where a function stops fitting in a reader's head.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "pdf_autofiller"
MAX_COMPLEXITY = 20


def _complexity_report() -> list[tuple[str, str, int]]:
    """Return (file, name, complexity) for every block radon can measure."""
    result = subprocess.run(
        [sys.executable, "-m", "radon", "cc", str(SRC), "-s", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip("radon is unavailable in this environment")

    import json

    blocks = []
    for path, entries in json.loads(result.stdout).items():
        if isinstance(entries, dict):  # radon reports errors as a dict
            continue
        for entry in entries:
            blocks.append((Path(path).name, entry["name"], entry["complexity"]))
    return blocks


def test_no_function_exceeds_the_complexity_budget():
    over = [
        f"{file}:{name} = {score}"
        for file, name, score in _complexity_report()
        if score > MAX_COMPLEXITY
    ]
    assert not over, (
        f"functions above the complexity budget of {MAX_COMPLEXITY}: {over}. "
        "Split the function rather than raising the budget."
    )


@pytest.mark.parametrize(
    "name,ceiling",
    [
        # These were the worst offenders; pin them so the split is not undone.
        ("fill_pdf", 10),
        ("cmd_inspect", 10),
        ("map_user_data_to_fields", 15),
    ],
)
def test_refactored_functions_stay_split(name, ceiling):
    scores = [score for _, block, score in _complexity_report() if block == name]
    assert scores, f"{name} not found — was it renamed without updating this test?"
    assert max(scores) <= ceiling, (
        f"{name} has grown back to {max(scores)} (ceiling {ceiling})"
    )
