"""
Comprehensive test runner for PDF autofiller.

Runs a lightweight smoke-check across the main modules without external services.
"""

import sys
import traceback
from importlib import import_module


RECOMMENDED_INSTALL_COMMAND = "pip install -r requirements-dev.txt"


def check_imports():
    """Check that all modules can be imported."""
    print("Testing imports...")
    all_passed = True

    try:
        import_module("pdf_autofiller.models")
        print("  ✓ Models imported")
    except Exception as e:
        print(f"  ✗ Models import failed: {e}")
        all_passed = False

    try:
        import_module("pdf_autofiller.pdf_reader")
        print("  ✓ PDF reader imported")
    except ImportError as e:
        if "pypdf" in str(e):
            print("  ⚠ PDF reader import failed: pypdf not installed")
            print(f"    Install with: {RECOMMENDED_INSTALL_COMMAND}")
        else:
            print(f"  ✗ PDF reader import failed: {e}")
            all_passed = False
    except Exception as e:
        print(f"  ✗ PDF reader import failed: {e}")
        all_passed = False

    try:
        import_module("pdf_autofiller.field_semantics")
        print("  ✓ Field semantics imported")
    except ImportError as e:
        if "openai" in str(e) or "pydantic" in str(e):
            print(f"  ⚠ Field semantics import failed: {e}")
            print(f"    Install with: {RECOMMENDED_INSTALL_COMMAND}")
        else:
            print(f"  ✗ Field semantics import failed: {e}")
            all_passed = False
    except Exception as e:
        print(f"  ✗ Field semantics import failed: {e}")
        all_passed = False

    try:
        import_module("pdf_autofiller.mapping")
        print("  ✓ Mapping imported")
    except ImportError as e:
        if "pydantic" in str(e):
            print("  ⚠ Mapping import failed: pydantic not installed")
            print(f"    Install with: {RECOMMENDED_INSTALL_COMMAND}")
        else:
            print(f"  ✗ Mapping import failed: {e}")
            all_passed = False
    except Exception as e:
        print(f"  ✗ Mapping import failed: {e}")
        all_passed = False

    try:
        import_module("pdf_autofiller.pdf_writer")
        print("  ✓ PDF writer imported")
    except ImportError as e:
        if "pypdf" in str(e):
            print("  ⚠ PDF writer import failed: pypdf not installed")
            print(f"    Install with: {RECOMMENDED_INSTALL_COMMAND}")
        else:
            print(f"  ✗ PDF writer import failed: {e}")
            all_passed = False
    except Exception as e:
        print(f"  ✗ PDF writer import failed: {e}")
        all_passed = False

    return all_passed


def check_mapping_functions():
    """Check mapping utility functions."""
    print("\nTesting mapping functions...")

    from pdf_autofiller.mapping import normalize_key, coerce_value, find_deterministic_match

    # Test normalize_key
    assert normalize_key("First-Name!") == "first_name"
    assert normalize_key("Email Address") == "email_address"
    print("  ✓ normalize_key works correctly")

    # Test coerce_value
    value, review = coerce_value("2024-01-15", "date")
    assert value == "2024-01-15" and review is False
    print("  ✓ coerce_value (date) works correctly")

    value, review = coerce_value("123", "number")
    assert value == "123" and review is False
    print("  ✓ coerce_value (number) works correctly")

    value, review = coerce_value("yes", "boolean")
    assert value == "true" and review is False
    print("  ✓ coerce_value (boolean) works correctly")

    # Test find_deterministic_match
    user_data = {"firstname": "John", "lastname": "Doe"}
    key, value, conf, reason, requires_review = find_deterministic_match("first_name", user_data, "string")
    assert key == "firstname" and value == "John"
    print("  ✓ find_deterministic_match works correctly")

    return True


def check_models():
    """Check Pydantic models."""
    print("\nTesting models...")

    from pdf_autofiller.models import (
        FormField, FieldSemantics, EnrichedFormField,
        FieldMappingDecision, MappingResult
    )

    # Test FormField
    field = FormField(
        name="txtFirstName",
        field_type="text",
        required=True,
        page_number=1
    )
    assert field.name == "txtFirstName"
    print("  ✓ FormField model works")

    # Test FieldSemantics
    semantics = FieldSemantics(
        semantic_meaning="first_name",
        expected_data_type="string",
        confidence_score=0.95
    )
    assert semantics.semantic_meaning == "first_name"
    print("  ✓ FieldSemantics model works")

    # Test EnrichedFormField
    enriched = EnrichedFormField(field=field, semantics=semantics)
    assert enriched.field.name == "txtFirstName"
    print("  ✓ EnrichedFormField model works")

    # Test FieldMappingDecision
    decision = FieldMappingDecision(
        field_name="txtFirstName",
        semantic_meaning="first_name",
        selected_value="John",
        confidence=0.95,
        reason="Direct match",
        requires_review=False
    )
    assert decision.selected_value == "John"
    print("  ✓ FieldMappingDecision model works")

    # Test MappingResult
    result = MappingResult(
        decisions=[decision],
        missing_required=[],
        unmapped_user_keys=[]
    )
    assert len(result.decisions) == 1
    print("  ✓ MappingResult model works")

    return True


def check_mapping_workflow():
    """Check the complete mapping workflow."""
    print("\nTesting mapping workflow...")

    from pdf_autofiller.models import (
        FormField, FieldSemantics, EnrichedFormField
    )
    from pdf_autofiller.mapping import map_user_data_to_fields

    # Create test enriched fields
    enriched_fields = [
        EnrichedFormField(
            field=FormField(
                name="txtFirstName",
                field_type="text",
                required=True,
                page_number=1
            ),
            semantics=FieldSemantics(
                semantic_meaning="first_name",
                expected_data_type="string",
                confidence_score=0.95
            )
        ),
        EnrichedFormField(
            field=FormField(
                name="txtLastName",
                field_type="text",
                required=True,
                page_number=1
            ),
            semantics=FieldSemantics(
                semantic_meaning="last_name",
                expected_data_type="string",
                confidence_score=0.95
            )
        ),
    ]

    # Test with matching user data
    user_data = {
        "firstname": "John",
        "lastname": "Doe"
    }

    result = map_user_data_to_fields(enriched_fields, user_data, strict=True)

    assert len(result.decisions) == 2
    assert result.decisions[0].selected_value == "John"
    assert result.decisions[1].selected_value == "Doe"
    assert len(result.missing_required) == 0
    print("  ✓ Mapping workflow works correctly")

    # Test with missing required field
    user_data_partial = {"firstname": "John"}
    result_partial = map_user_data_to_fields(enriched_fields, user_data_partial, strict=True)
    assert len(result_partial.missing_required) == 1
    print("  ✓ Missing required field detection works")

    return True


def check_semantic_client():
    """Check semantic client initialization."""
    print("\nTesting semantic client...")

    from pdf_autofiller.field_semantics import SemanticClient

    client = SemanticClient()
    available = client.is_available()

    if available:
        print("  ✓ Semantic client available (provider key set)")
    else:
        print("  ⚠ Semantic client not available (provider key not set)")
        print("    This is expected if provider credentials are not configured")

    return True


def main() -> int:
    """Run the local smoke checks."""
    print("="*60)
    print("PDF Autofiller - Smoke Check")
    print("="*60)

    checks = [
        ("Imports", check_imports),
        ("Models", check_models),
        ("Mapping Functions", check_mapping_functions),
        ("Mapping Workflow", check_mapping_workflow),
        ("Semantic Client", check_semantic_client),
    ]

    results = []
    for name, check_func in checks:
        try:
            result = check_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n  ✗ {name} failed with exception: {e}")
            traceback.print_exc()
            results.append((name, False))

    print("\n" + "="*60)
    print("Test Results Summary")
    print("="*60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")
    print("="*60)

    if passed == total:
        print("\n✓ All tests passed!")
        return 0
    else:
        print(f"\n✗ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
