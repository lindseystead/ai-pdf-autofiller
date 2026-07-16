"""
Demo script to test the full PDF autofiller workflow.
"""

import json
import sys
from pathlib import Path

from pdf_autofiller.pdf_reader import read_pdf
from pdf_autofiller.field_semantics import infer_field_semantics
from pdf_autofiller.mapping import map_user_data_to_fields, normalize_key
from pdf_autofiller.pdf_writer import UnresolvedRequiredFieldsError, fill_pdf


def run_demo_workflow(pdf_path: Path, user_data: dict[str, object]) -> bool:
    """
    Run the complete workflow from PDF reading to filling.

    Args:
        pdf_path: Path to input PDF
        user_data: Dictionary of user data to map
    """
    print(f"\n{'='*60}")
    print("Running PDF Autofiller Workflow")
    print(f"{'='*60}\n")

    # Step 1: Read PDF
    print("Step 1: Reading PDF structure...")
    try:
        structure = read_pdf(pdf_path)
        print("✓ PDF loaded successfully")
        print(f"  - Pages: {structure.metadata.num_pages}")
        print(f"  - Form fields found: {len(structure.form_fields)}")
        print(f"  - Text regions: {len(structure.text_regions)}")

        if structure.form_fields:
            print("\n  Form fields:")
            for field in structure.form_fields[:5]:  # Show first 5
                print(f"    - {field.name} ({field.field_type}, required={field.required})")
            if len(structure.form_fields) > 5:
                print(f"    ... and {len(structure.form_fields) - 5} more")
    except FileNotFoundError:
        print(f"✗ PDF file not found: {pdf_path}")
        return False
    except Exception as e:
        print(f"✗ Error reading PDF: {e}")
        return False

    # Step 2: Infer semantics (if provider credentials are available)
    print("\nStep 2: Inferring field semantics...")
    enriched_fields = []
    semantics_available = False

    for field in structure.form_fields:
        try:
            enriched = infer_field_semantics(field)
            enriched_fields.append(enriched)
            semantics_available = True
        except RuntimeError:
            # Provider client not available, skip semantic inference
            print("  ⚠ Provider API key not configured, skipping semantic inference")
            print("  (Set MODEL_PROVIDER_API_KEY environment variable to enable)")
            break
        except Exception as e:
            print(f"  ⚠ Error inferring semantics for {field.name}: {e}")
            break

    if not semantics_available:
        print("  ⚠ Semantic inference skipped - using field names directly")
        # Create mock enriched fields for testing
        from pdf_autofiller.models import EnrichedFormField, FieldSemantics
        for field in structure.form_fields:
            enriched_fields.append(EnrichedFormField(
                field=field,
                semantics=FieldSemantics(
                    semantic_meaning=normalize_field_name(field.name),
                    expected_data_type="string",
                    confidence_score=0.5
                )
            ))

    print(f"✓ Processed {len(enriched_fields)} fields")

    # Step 3: Map user data
    print("\nStep 3: Mapping user data to fields...")
    print(f"  User data keys: {list(user_data.keys())}")

    try:
        mapping_result = map_user_data_to_fields(
            enriched_fields,
            user_data,
            strict=True  # Use deterministic matching only for demo
        )

        print("✓ Mapping complete")
        print(f"  - Decisions made: {len(mapping_result.decisions)}")
        print(f"  - Missing required: {len(mapping_result.missing_required)}")
        print(f"  - Unmapped keys: {len(mapping_result.unmapped_user_keys)}")

        if mapping_result.decisions:
            print("\n  Mapping decisions:")
            for decision in mapping_result.decisions[:5]:
                status = "⚠ REVIEW" if decision.requires_review else "✓"
                print(f"    {status} {decision.field_name}: '{decision.selected_value}' "
                      f"(confidence: {decision.confidence:.2f})")
            if len(mapping_result.decisions) > 5:
                print(f"    ... and {len(mapping_result.decisions) - 5} more")

        if mapping_result.missing_required:
            print(f"\n  ⚠ Missing required fields: {mapping_result.missing_required}")

        if mapping_result.unmapped_user_keys:
            print(f"\n  ⚠ Unmapped user keys: {mapping_result.unmapped_user_keys}")

    except (RuntimeError, ValueError) as e:
        print(f"✗ Error mapping data: {e}")
        return False

    # Step 4: Fill PDF
    print("\nStep 4: Filling PDF...")
    output_path = pdf_path.parent / f"{pdf_path.stem}_filled.pdf"

    try:
        fill_pdf(pdf_path, output_path, mapping_result)
        print("✓ PDF filled successfully")
        print(f"  Output: {output_path}")
        return True
    except UnresolvedRequiredFieldsError as e:
        print(f"✗ Error filling PDF: {e}")
        print("  This is expected if required fields are missing")
        return False
    except OSError as e:
        print(f"✗ Error writing output PDF: {e}")
        return False


def normalize_field_name(name: str) -> str:
    """Mirror the API fallback semantics for local demo runs."""
    normalized = normalize_key(name)
    normalized = normalized.removeprefix("txt_")
    normalized = normalized.removeprefix("txt")
    return normalized or "unknown_field"


def main() -> int:
    """CLI entrypoint for the demo workflow."""
    if len(sys.argv) < 2:
        print("Usage: PYTHONPATH=src python -m scripts.demo_workflow <path_to_pdf> [user_data_json]")
        print("\nExample:")
        print(
            '  PYTHONPATH=src python -m scripts.demo_workflow form.pdf '
            '\'{"firstname": "John", "lastname": "Doe"}\''
        )
        return 1

    pdf_path = Path(sys.argv[1])

    if len(sys.argv) >= 3:
        try:
            user_data = json.loads(sys.argv[2])
        except json.JSONDecodeError as exc:
            print(f"Invalid JSON for user_data: {exc}")
            return 1
    else:
        # Default test data
        user_data = {
            "firstname": "John",
            "lastname": "Doe",
            "dob": "1990-05-15",
            "email": "john.doe@example.com"
        }

    success = run_demo_workflow(pdf_path, user_data)

    if success:
        print(f"\n{'='*60}")
        print("✓ Workflow completed successfully!")
        print(f"{'='*60}\n")
    else:
        print(f"\n{'='*60}")
        print("✗ Workflow completed with errors")
        print(f"{'='*60}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
