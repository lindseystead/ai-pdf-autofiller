"""
Create synthetic corpus PDFs used by hit-rate fixtures.

Generates ``samples/hr_intake_sample.pdf`` (HR-like AcroForm). The bundled
``samples/sample_form.pdf`` remains produced by ``create_sample_form.py``.
"""

from pathlib import Path


def create_hr_intake_form(output_path: Path) -> None:
    """Create an HR-like fillable PDF with text fields and one checkbox."""
    from pypdf import PdfWriter
    from pypdf.generic import (
        ArrayObject,
        BooleanObject,
        DictionaryObject,
        NameObject,
        NumberObject,
        TextStringObject,
    )

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        }
    )
    font_ref = writer._add_object(font)

    acro_form = DictionaryObject(
        {
            NameObject("/Fields"): ArrayObject(),
            NameObject("/NeedAppearances"): BooleanObject(True),
            NameObject("/DA"): TextStringObject("/Helv 0 Tf 0 g"),
            NameObject("/DR"): DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject(
                        {NameObject("/Helv"): font_ref}
                    )
                }
            ),
        }
    )
    writer._root_object.update({NameObject("/AcroForm"): acro_form})

    text_fields = [
        {"name": "txtEmployeeName", "y": 700, "required": True, "width": 300},
        {"name": "txtSSN", "y": 650, "required": True, "width": 200},
        {"name": "txtEmployer", "y": 600, "required": True, "width": 300},
        {"name": "txtJobTitle", "y": 550, "required": False, "width": 250},
        {"name": "txtStartDate", "y": 500, "required": False, "width": 200},
    ]

    annotations = ArrayObject()
    x = 100
    for field_def in text_fields:
        height = 20
        field = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/Rect"): ArrayObject(
                    [
                        NumberObject(x),
                        NumberObject(792 - field_def["y"] - height),
                        NumberObject(x + field_def["width"]),
                        NumberObject(792 - field_def["y"]),
                    ]
                ),
                NameObject("/FT"): NameObject("/Tx"),
                NameObject("/T"): TextStringObject(field_def["name"]),
                NameObject("/Ff"): NumberObject(0x02 if field_def["required"] else 0),
                NameObject("/F"): NumberObject(4),
            }
        )
        field_ref = writer._add_object(field)
        annotations.append(field_ref)
        acro_form[NameObject("/Fields")].append(field_ref)

    normal = DictionaryObject(
        {NameObject("/Yes"): DictionaryObject(), NameObject("/Off"): DictionaryObject()}
    )
    checkbox = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject("/Btn"),
            NameObject("/T"): TextStringObject("chkConsent"),
            NameObject("/Rect"): ArrayObject(
                [NumberObject(100), NumberObject(420), NumberObject(120), NumberObject(440)]
            ),
            NameObject("/AP"): DictionaryObject({NameObject("/N"): normal}),
            NameObject("/AS"): NameObject("/Off"),
            NameObject("/V"): NameObject("/Off"),
            NameObject("/F"): NumberObject(4),
        }
    )
    checkbox_ref = writer._add_object(checkbox)
    annotations.append(checkbox_ref)
    acro_form[NameObject("/Fields")].append(checkbox_ref)

    page[NameObject("/Annots")] = annotations

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)
    print(f"Created HR intake sample: {output_path}")


def main() -> None:
    samples_dir = Path(__file__).resolve().parent.parent / "samples"
    create_hr_intake_form(samples_dir / "hr_intake_sample.pdf")


if __name__ == "__main__":
    main()
