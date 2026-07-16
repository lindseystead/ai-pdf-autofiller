"""
Create a sample fillable PDF form for testing.
"""

import importlib.util
from pathlib import Path

REPORTLAB_AVAILABLE = (
    importlib.util.find_spec("reportlab")
    is not None
)


def create_sample_form_pypdf(output_path: Path):
    """
    Create a sample fillable PDF form using pypdf.

    This creates a simple form with text fields that can be filled.
    """
    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject, BooleanObject, DictionaryObject, NameObject
    from pypdf.generic import NumberObject, TextStringObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)

    # pypdf does not provide a high-level AcroForm builder, so we construct the
    # minimum required dictionaries directly and register a standard Helvetica
    # font resource to avoid warnings when fields are later filled.
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
        NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
    })
    font_ref = writer._add_object(font)

    # Create AcroForm
    acro_form = DictionaryObject({
        NameObject("/Fields"): ArrayObject(),
        NameObject("/NeedAppearances"): BooleanObject(True),
        NameObject("/DA"): TextStringObject("/Helv 0 Tf 0 g"),
        NameObject("/DR"): DictionaryObject({
            NameObject("/Font"): DictionaryObject({
                NameObject("/Helv"): font_ref,
            })
        }),
    })

    writer._root_object.update({
        NameObject("/AcroForm"): acro_form
    })

    # Field definitions
    fields = [
        {
            "name": "txtFirstName",
            "x": 100,
            "y": 700,
            "width": 200,
            "height": 20,
            "required": True
        },
        {
            "name": "txtLastName",
            "x": 350,
            "y": 700,
            "width": 200,
            "height": 20,
            "required": True
        },
        {
            "name": "txtDOB",
            "x": 100,
            "y": 650,
            "width": 200,
            "height": 20,
            "required": True
        },
        {
            "name": "txtEmail",
            "x": 100,
            "y": 600,
            "width": 300,
            "height": 20,
            "required": False
        },
        {
            "name": "txtPhone",
            "x": 100,
            "y": 550,
            "width": 200,
            "height": 20,
            "required": False
        },
    ]

    # Create annotations/widgets for each field
    annotations = ArrayObject()

    for i, field_def in enumerate(fields):
        # Create field dictionary
        field = DictionaryObject({
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Widget"),
            NameObject("/Rect"): ArrayObject([
                NumberObject(field_def["x"]),
                NumberObject(792 - field_def["y"] - field_def["height"]),
                NumberObject(field_def["x"] + field_def["width"]),
                NumberObject(792 - field_def["y"])
            ]),
            NameObject("/FT"): NameObject("/Tx"),  # Text field
            NameObject("/T"): TextStringObject(field_def["name"]),
            NameObject("/Ff"): NumberObject(0x02 if field_def["required"] else 0),
            NameObject("/F"): NumberObject(4),  # Printable
        })

        # Add to annotations
        field_ref = writer._add_object(field)
        annotations.append(field_ref)

        # Add to form fields
        acro_form[NameObject("/Fields")].append(field_ref)

    # Add annotations to page
    page[NameObject("/Annots")] = annotations

    # Write PDF
    with output_path.open("wb") as output_file:
        writer.write(output_file)

    print(f"Created sample form: {output_path}")


def create_simple_form_with_text(output_path: Path):
    """
    Create a simple PDF form with visible labels using reportlab.
    Falls back to pypdf-only method if reportlab not available.
    """
    if REPORTLAB_AVAILABLE:
        try:
            from reportlab.lib import colors
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter

            c = canvas.Canvas(str(output_path), pagesize=letter)
            _, height = letter
            form = c.acroForm

            # Title
            c.setFont("Helvetica-Bold", 20)
            c.drawString(100, height - 50, "Sample Job Application Form")

            # Instructions
            c.setFont("Helvetica", 10)
            c.drawString(100, height - 80, "Please fill out all required fields marked with *")

            fields = [
                {
                    "label": "First Name *",
                    "name": "txtFirstName",
                    "required": True,
                    "x": 100,
                    "y": height - 165,
                    "width": 200,
                },
                {
                    "label": "Last Name *",
                    "name": "txtLastName",
                    "required": True,
                    "x": 350,
                    "y": height - 165,
                    "width": 200,
                },
                {
                    "label": "Date of Birth * (YYYY-MM-DD)",
                    "name": "txtDOB",
                    "required": True,
                    "x": 100,
                    "y": height - 225,
                    "width": 220,
                },
                {
                    "label": "Email Address",
                    "name": "txtEmail",
                    "required": False,
                    "x": 100,
                    "y": height - 285,
                    "width": 300,
                },
                {
                    "label": "Phone Number",
                    "name": "txtPhone",
                    "required": False,
                    "x": 100,
                    "y": height - 345,
                    "width": 220,
                },
            ]

            c.setFont("Helvetica", 12)
            for field in fields:
                c.drawString(field["x"], field["y"] + 28, field["label"])
                form.textfield(
                    name=field["name"],
                    x=field["x"],
                    y=field["y"],
                    width=field["width"],
                    height=22,
                    fontName="Helvetica",
                    fontSize=11,
                    textColor=colors.black,
                    borderColor=colors.HexColor("#4b5563"),
                    fillColor=colors.white,
                    borderWidth=1,
                    forceBorder=True,
                    fieldFlags="required" if field["required"] else "",
                )

            c.save()
            print(f"Created sample form with labels: {output_path}")
            return True
        except Exception as exc:
            print(f"ReportLab method failed: {exc}; using pypdf method")
            return False

    return False


def main():
    """Create a sample fillable PDF form."""
    # Output to samples directory
    samples_dir = Path(__file__).parent.parent / "samples"
    samples_dir.mkdir(exist_ok=True)
    output_path = samples_dir / "sample_form.pdf"

    print("Creating sample fillable PDF form...")
    print("=" * 60)

    # Try reportlab first (better visual result)
    if not create_simple_form_with_text(output_path):
        # Fall back to pypdf-only method
        print("\nUsing pypdf method (minimal visual, but fillable)...")
        create_sample_form_pypdf(output_path)

    print("\n" + "=" * 60)
    print(f"Sample form created: {output_path}")
    print("\nForm fields included:")
    print("  - txtFirstName (required)")
    print("  - txtLastName (required)")
    print("  - txtDOB (required)")
    print("  - txtEmail (optional)")
    print("  - txtPhone (optional)")
    print("\nTest it with:")
    print(
        f"  PYTHONPATH=src python -m scripts.demo_workflow {output_path} "
        '\'{"firstname": "Alex", "lastname": "Example", "dob": "1990-01-01", '
        '"email": "test@example.com"}\''
    )


if __name__ == "__main__":
    main()
