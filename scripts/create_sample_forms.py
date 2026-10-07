"""
Create the synthetic fillable PDFs in ``samples/``.

Every sample is a one-page AcroForm with a visible title, field labels and
boxes, so a filled result reads like a real form. They are synthetic: field
names resemble real form families but these are not official IRS/vendor PDFs
and must not be marketed as such.

Field names are a contract with tests/fixtures/corpus/cases.json — change them
only together with that file.

Run from the repo root: ``python3 -m scripts.create_sample_forms``
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

PAGE_WIDTH = 612
PAGE_HEIGHT = 792
MARGIN_LEFT = 72
FIRST_ROW_TOP = 130  # distance from the top edge to the first label
ROW_HEIGHT = 50
LABEL_GAP = 14  # label baseline sits this far above its box
BOX_HEIGHT = 20
CHECKBOX_SIZE = 14
DISCLAIMER = "Synthetic sample for testing PDF Autofiller. Not an official form."


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    width: int = 250
    required: bool = False
    checkbox: bool = False


def _pdf_string(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return f"({escaped})"


def _text(font: str, size: int, x: float, y: float, text: str) -> str:
    return f"BT /{font} {size} Tf {x} {y} Td {_pdf_string(text)} Tj ET"


def _checkbox_appearance(writer: PdfWriter, zapf_dingbats: object, *, checked: bool) -> object:
    """Form XObject for one checkbox state: a ZapfDingbats check mark, or nothing."""
    stream = DecodedStreamObject()
    stream.set_data(b"q BT /ZaDb 11 Tf 0 g 2 3 Td (4) Tj ET Q" if checked else b"")
    stream.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Form"),
            NameObject("/BBox"): ArrayObject(
                [NumberObject(0), NumberObject(0)] + [NumberObject(CHECKBOX_SIZE)] * 2
            ),
            NameObject("/Resources"): DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/ZaDb"): zapf_dingbats})}
            ),
        }
    )
    return writer._add_object(stream)


def _widget(
    writer: PdfWriter, zapf_dingbats: object, name: str, rect: list[float], *, required: bool, checkbox: bool
) -> DictionaryObject:
    widget = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/T"): TextStringObject(name),
            NameObject("/Rect"): ArrayObject([NumberObject(round(v)) for v in rect]),
            NameObject("/F"): NumberObject(4),  # print
        }
    )
    if checkbox:
        off_on = DictionaryObject(
            {
                NameObject("/Yes"): _checkbox_appearance(writer, zapf_dingbats, checked=True),
                NameObject("/Off"): _checkbox_appearance(writer, zapf_dingbats, checked=False),
            }
        )
        widget[NameObject("/FT")] = NameObject("/Btn")
        widget[NameObject("/AP")] = DictionaryObject({NameObject("/N"): off_on})
        widget[NameObject("/AS")] = NameObject("/Off")
        widget[NameObject("/V")] = NameObject("/Off")
    else:
        widget[NameObject("/FT")] = NameObject("/Tx")
        widget[NameObject("/Ff")] = NumberObject(0x02 if required else 0)
    return widget


def build_form(output_path: Path, title: str, fields: list[Field]) -> None:
    """Write a one-page form with ``fields`` stacked top to bottom, in order."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)

    helvetica = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            }
        )
    )
    zapf_dingbats = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/ZapfDingbats"),
            }
        )
    )
    helvetica_bold = writer._add_object(
        DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica-Bold"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            }
        )
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): helvetica, NameObject("/F2"): helvetica_bold}
            )
        }
    )

    acro_form = DictionaryObject(
        {
            NameObject("/Fields"): ArrayObject(),
            NameObject("/NeedAppearances"): BooleanObject(True),
            NameObject("/DA"): TextStringObject("/Helv 11 Tf 0 g"),
            NameObject("/DR"): DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject(
                        # ZaDb draws the check mark when a checkbox is set.
                        {NameObject("/Helv"): helvetica, NameObject("/ZaDb"): zapf_dingbats}
                    )
                }
            ),
        }
    )
    writer._root_object[NameObject("/AcroForm")] = acro_form

    ops = [
        _text("F2", 18, MARGIN_LEFT, PAGE_HEIGHT - 72, title),
        _text("F1", 9, MARGIN_LEFT, PAGE_HEIGHT - 90, DISCLAIMER),
        "0.3 0.33 0.39 RG 0.75 w",  # gray box borders
    ]
    annotations = ArrayObject()

    for row, field in enumerate(fields):
        label_baseline = PAGE_HEIGHT - FIRST_ROW_TOP - row * ROW_HEIGHT
        label = f"{field.label} *" if field.required else field.label
        if field.checkbox:
            bottom = label_baseline - 3
            rect = [MARGIN_LEFT, bottom, MARGIN_LEFT + CHECKBOX_SIZE, bottom + CHECKBOX_SIZE]
            ops.append(_text("F1", 10, MARGIN_LEFT + CHECKBOX_SIZE + 8, label_baseline, label))
        else:
            bottom = label_baseline - LABEL_GAP - BOX_HEIGHT + 10
            rect = [MARGIN_LEFT, bottom, MARGIN_LEFT + field.width, bottom + BOX_HEIGHT]
            ops.append(_text("F1", 10, MARGIN_LEFT, label_baseline, label))
        ops.append(f"{rect[0]} {rect[1]} {rect[2] - rect[0]} {rect[3] - rect[1]} re S")

        widget_ref = writer._add_object(
            _widget(writer, zapf_dingbats, field.name, rect, required=field.required, checkbox=field.checkbox)
        )
        annotations.append(widget_ref)
        acro_form[NameObject("/Fields")].append(widget_ref)

    content = DecodedStreamObject()
    content.set_data("\n".join(ops).encode("latin-1"))
    page[NameObject("/Contents")] = writer._add_object(content)
    page[NameObject("/Annots")] = annotations

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)
    print(f"Created {output_path}")


SAMPLES: dict[str, tuple[str, list[Field]]] = {
    "sample_form.pdf": (
        "Sample Application Form",
        [
            Field("txtFirstName", "First name", 220, required=True),
            Field("txtLastName", "Last name", 220, required=True),
            Field("txtDOB", "Date of birth (YYYY-MM-DD)", 160, required=True),
            Field("txtEmail", "Email address", 300),
            Field("txtPhone", "Phone number", 180),
        ],
    ),
    "hr_intake_sample.pdf": (
        "New Employee Intake",
        [
            Field("txtEmployeeName", "Employee name", 300, required=True),
            Field("txtSSN", "Social Security number", 180, required=True),
            Field("txtEmployer", "Employer", 300, required=True),
            Field("txtJobTitle", "Job title", 250),
            Field("txtStartDate", "Start date", 160),
            Field("chkConsent", "I consent to a background check", checkbox=True),
        ],
    ),
    "w9_shaped_sample.pdf": (
        "Taxpayer Information (W-9-shaped sample)",
        [
            Field("txtNameLine1", "Name (as shown on your income tax return)", 340, required=True),
            Field("txtBusinessName", "Business name, if different", 340),
            Field("txtEIN", "Employer identification number", 180, required=True),
            Field("txtAddr1", "Address (number, street, apt.)", 340, required=True),
            Field("txtCity", "City", 220, required=True),
            Field("txtState", "State", 80, required=True),
            Field("txtZIP", "ZIP code", 120, required=True),
        ],
    ),
    "address_contact_sample.pdf": (
        "Contact Details",
        [
            Field("txtStreet", "Street address", 340, required=True),
            Field("txtAddress2", "Address line 2", 340),
            Field("txtTown", "Town / city", 220, required=True),
            Field("txtProvince", "Province / state", 120, required=True),
            Field("txtPostcode", "Postcode", 120, required=True),
            Field("txtEmail", "Email", 280, required=True),
            Field("txtMobile", "Mobile", 180),
        ],
    ),
    "hr_hire_alias_sample.pdf": (
        "New Hire Notice",
        [
            Field("txtEmployeeName", "Employee name", 300, required=True),
            Field("txtStartDate", "Start date", 160, required=True),
            Field("txtManager", "Manager", 250),
            Field("txtDepartment", "Department", 220),
            Field("txtEmployeeId", "Employee ID", 160),
        ],
    ),
    # Field names come from an anonymized vendor inspect dump; the layout is
    # synthetic. Proves mapping works on export-style names, not only txt*.
    "vendor_opaque_sample.pdf": (
        "Vendor Onboarding Form",
        [
            Field("EmployeeFirstName_AF_text", "First name", 280, required=True),
            Field("EmployeeLastName_AF_text", "Last name", 280, required=True),
            Field("DateOfBirth_AF_date", "Date of birth", 160, required=True),
            Field("EmailAddress_AF_text", "Email address", 280),
            Field("PrimaryPhone_AF_text", "Primary phone", 180),
        ],
    ),
}


def main() -> None:
    samples_dir = Path(__file__).resolve().parent.parent / "samples"
    for filename, (title, fields) in SAMPLES.items():
        build_form(samples_dir / filename, title, fields)


if __name__ == "__main__":
    main()
