"""OpenAPI error catalog and ERROR_CATALOG consistency."""

from pdf_autofiller.api.errors import ERROR_CATALOG, openapi_error_responses
from pdf_autofiller.api_service import app


def test_error_catalog_covers_documented_codes():
    expected = {
        "request_validation_error",
        "invalid_user_data_json",
        "invalid_user_data_type",
        "unsupported_media_type",
        "invalid_pdf_signature",
        "payload_too_large",
        "pdf_too_many_pages",
        "pdf_processing_timeout",
        "rate_limited",
        "unauthorized",
        "server_auth_config_error",
        "required_fields_unresolved",
        "pdf_fill_failed",
        "pdf_preview_failed",
        "pdf_inspect_failed",
        "sample_not_found",
    }
    assert set(ERROR_CATALOG) == expected


def test_openapi_fill_documents_error_envelope():
    schema = app.openapi()
    fill_responses = schema["paths"]["/fill"]["post"]["responses"]
    assert "401" in fill_responses
    assert "429" in fill_responses
    assert "422" in fill_responses
    assert "415" in fill_responses
    assert "application/pdf" in fill_responses["200"]["content"]
    assert "application/json" in fill_responses["200"]["content"]
    # Error responses use the shared envelope model
    assert "ApiErrorEnvelope" in schema["components"]["schemas"]


def test_openapi_error_responses_groups_by_status():
    responses = openapi_error_responses("unauthorized", "rate_limited", "pdf_fill_failed")
    assert set(responses) == {401, 429, 500}
    assert "`unauthorized`" in responses[401]["description"]
