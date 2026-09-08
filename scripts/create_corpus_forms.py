"""
Create synthetic corpus PDFs used by hit-rate fixtures.

These are intentionally synthetic. They prove deterministic alias matching on
field-name patterns that resemble real form families — they are not official
IRS/vendor PDFs and must not be marketed as such.
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    BooleanObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)


def _new_writer_with_acroform() -> tuple[PdfWriter, DictionaryObject, object]:
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
                {NameObject("/Font"): DictionaryObject({NameObject("/Helv"): font_ref})}
            ),
        }
    )
    writer._root_object.update({NameObject("/AcroForm"): acro_form})
    return writer, acro_form, page


def _add_text_field(
    writer: PdfWriter,
    acro_form: DictionaryObject,
    annotations: ArrayObject,
    *,
    name: str,
    y: int,
    width: int = 250,
    required: bool = False,
    x: int = 100,
) -> None:
    height = 20
    field = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Rect"): ArrayObject(
                [
                    NumberObject(x),
                    NumberObject(792 - y - height),
                    NumberObject(x + width),
                    NumberObject(792 - y),
                ]
            ),
            NameObject("/FT"): NameObject("/Tx"),
            NameObject("/T"): TextStringObject(name),
            NameObject("/Ff"): NumberObject(0x02 if required else 0),
            NameObject("/F"): NumberObject(4),
        }
    )
    field_ref = writer._add_object(field)
    annotations.append(field_ref)
    acro_form[NameObject("/Fields")].append(field_ref)


def _add_checkbox(
    writer: PdfWriter,
    acro_form: DictionaryObject,
    annotations: ArrayObject,
    *,
    name: str,
    y: int,
) -> None:
    normal = DictionaryObject(
        {NameObject("/Yes"): DictionaryObject(), NameObject("/Off"): DictionaryObject()}
    )
    checkbox = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/FT"): NameObject("/Btn"),
            NameObject("/T"): TextStringObject(name),
            NameObject("/Rect"): ArrayObject(
                [NumberObject(100), NumberObject(792 - y - 20), NumberObject(120), NumberObject(792 - y)]
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


def create_hr_intake_form(output_path: Path) -> None:
    """Create an HR-like fillable PDF with text fields and one checkbox."""
    writer, acro_form, page = _new_writer_with_acroform()
    annotations = ArrayObject()
    for field_def in (
        {"name": "txtEmployeeName", "y": 700, "required": True, "width": 300},
        {"name": "txtSSN", "y": 650, "required": True, "width": 200},
        {"name": "txtEmployer", "y": 600, "required": True, "width": 300},
        {"name": "txtJobTitle", "y": 550, "required": False, "width": 250},
        {"name": "txtStartDate", "y": 500, "required": False, "width": 200},
    ):
        _add_text_field(
            writer,
            acro_form,
            annotations,
            name=field_def["name"],
            y=field_def["y"],
            width=field_def["width"],
            required=field_def["required"],
        )
    _add_checkbox(writer, acro_form, annotations, name="chkConsent", y=450)
    page[NameObject("/Annots")] = annotations
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)
    print(f"Created HR intake sample: {output_path}")


def create_w9_shaped_form(output_path: Path) -> None:
    """Synthetic W-9-shaped AcroForm (not an IRS form)."""
    writer, acro_form, page = _new_writer_with_acroform()
    annotations = ArrayObject()
    for field_def in (
        {"name": "txtNameLine1", "y": 700, "required": True, "width": 320},
        {"name": "txtBusinessName", "y": 650, "required": False, "width": 320},
        {"name": "txtEIN", "y": 600, "required": True, "width": 180},
        {"name": "txtAddr1", "y": 550, "required": True, "width": 320},
        {"name": "txtCity", "y": 500, "required": True, "width": 200},
        {"name": "txtState", "y": 450, "required": True, "width": 80},
        {"name": "txtZIP", "y": 400, "required": True, "width": 120},
    ):
        _add_text_field(
            writer,
            acro_form,
            annotations,
            name=field_def["name"],
            y=field_def["y"],
            width=field_def["width"],
            required=field_def["required"],
        )
    page[NameObject("/Annots")] = annotations
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)
    print(f"Created W-9-shaped sample: {output_path}")


def create_address_contact_form(output_path: Path) -> None:
    """Address/contact cluster for built-in alias coverage."""
    writer, acro_form, page = _new_writer_with_acroform()
    annotations = ArrayObject()
    for field_def in (
        {"name": "txtStreet", "y": 700, "required": True, "width": 320},
        {"name": "txtAddress2", "y": 650, "required": False, "width": 320},
        {"name": "txtTown", "y": 600, "required": True, "width": 200},
        {"name": "txtProvince", "y": 550, "required": True, "width": 80},
        {"name": "txtPostcode", "y": 500, "required": True, "width": 120},
        {"name": "txtEmail", "y": 450, "required": True, "width": 260},
        {"name": "txtMobile", "y": 400, "required": False, "width": 180},
    ):
        _add_text_field(
            writer,
            acro_form,
            annotations,
            name=field_def["name"],
            y=field_def["y"],
            width=field_def["width"],
            required=field_def["required"],
        )
    page[NameObject("/Annots")] = annotations
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)
    print(f"Created address/contact sample: {output_path}")


def create_hr_hire_date_alias_form(output_path: Path) -> None:
    """HR pack hire_date → start_date without AI."""
    writer, acro_form, page = _new_writer_with_acroform()
    annotations = ArrayObject()
    for field_def in (
        {"name": "txtEmployeeName", "y": 700, "required": True, "width": 300},
        {"name": "txtStartDate", "y": 650, "required": True, "width": 180},
        {"name": "txtManager", "y": 600, "required": False, "width": 250},
        {"name": "txtDepartment", "y": 550, "required": False, "width": 200},
        {"name": "txtEmployeeId", "y": 500, "required": False, "width": 160},
    ):
        _add_text_field(
            writer,
            acro_form,
            annotations,
            name=field_def["name"],
            y=field_def["y"],
            width=field_def["width"],
            required=field_def["required"],
        )
    page[NameObject("/Annots")] = annotations
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)
    print(f"Created HR hire-date alias sample: {output_path}")


def create_vendor_opaque_form(output_path: Path) -> None:
    """Blank page with field names taken from an anonymized vendor inspect dump.

    Layout is synthetic (not the vendor PDF). Names are preserved as evidence that
    mapping works on opaque export-style widgets, not only our ``txt*`` demos.
    """
    writer, acro_form, page = _new_writer_with_acroform()
    annotations = ArrayObject()
    for field_def in (
        {"name": "EmployeeFirstName_AF_text", "y": 700, "required": True, "width": 280},
        {"name": "EmployeeLastName_AF_text", "y": 650, "required": True, "width": 280},
        {"name": "DateOfBirth_AF_date", "y": 600, "required": True, "width": 160},
        {"name": "EmailAddress_AF_text", "y": 550, "required": False, "width": 280},
        {"name": "PrimaryPhone_AF_text", "y": 500, "required": False, "width": 180},
    ):
        _add_text_field(
            writer,
            acro_form,
            annotations,
            name=field_def["name"],
            y=field_def["y"],
            width=field_def["width"],
            required=field_def["required"],
        )
    page[NameObject("/Annots")] = annotations
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("wb") as handle:
        writer.write(handle)
    print(f"Created vendor-opaque sample: {output_path}")


def main() -> None:
    samples_dir = Path(__file__).resolve().parent.parent / "samples"
    create_hr_intake_form(samples_dir / "hr_intake_sample.pdf")
    create_w9_shaped_form(samples_dir / "w9_shaped_sample.pdf")
    create_address_contact_form(samples_dir / "address_contact_sample.pdf")
    create_hr_hire_date_alias_form(samples_dir / "hr_hire_alias_sample.pdf")
    create_vendor_opaque_form(samples_dir / "vendor_opaque_sample.pdf")


if __name__ == "__main__":
    main()
