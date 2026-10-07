"""Guard the bundled sample PDFs against regressing to blank, unlabeled pages."""

from pathlib import Path

import pytest
from pypdf import PdfReader

from scripts.create_sample_forms import SAMPLES

SAMPLES_DIR = Path("samples")


@pytest.mark.parametrize("filename", sorted(SAMPLES))
def test_sample_matches_generator_and_is_readable(filename: str):
    title, fields = SAMPLES[filename]
    reader = PdfReader(SAMPLES_DIR / filename)
    page = reader.pages[0]

    text = page.extract_text()
    assert title in text, "sample has no visible title; regenerate with scripts.create_sample_forms"
    for field in fields:
        assert field.label in text

    assert set(reader.get_fields()) == {field.name for field in fields}

    # Widgets sit on the page, stacked top to bottom in generator order.
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    tops = []
    for annot in page["/Annots"]:
        left, bottom, right, top = (float(v) for v in annot.get_object()["/Rect"])
        assert 0 <= left < right <= width and 0 <= bottom < top <= height
        tops.append(top)
    assert tops == sorted(tops, reverse=True)


def test_sample_checkbox_draws_a_check_mark_when_checked():
    reader = PdfReader(SAMPLES_DIR / "hr_intake_sample.pdf")
    (checkbox,) = (a.get_object() for a in reader.pages[0]["/Annots"] if a.get_object().get("/FT") == "/Btn")
    states = checkbox["/AP"]["/N"]
    on = states["/Yes"].get_object().get_data()
    off = states["/Off"].get_object().get_data()
    assert b"ZaDb" in on and b"Tj" in on  # a ZapfDingbats check mark is drawn
    assert b"Tj" not in off  # unchecked draws nothing
