"""Exercise the real preview-to-fill contract with synthetic AcroForms."""

import io
import json
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from pypdf.generic import DecodedStreamObject, NameObject

from pdf_autofiller import field_semantics
from pdf_autofiller.api import config
from pdf_autofiller.api.app import create_app
from pdf_autofiller.api.security import reset_rate_limit_state

from .form_factory import FormBuilder


@pytest.mark.parametrize("provider", ["stub", "live"])
def test_ai_preview_review_and_fill(provider, tmp_path, monkeypatch):
    calls = []
    if provider == "live":
        if os.getenv("RUN_LIVE_AI_EVAL") != "1":
            pytest.skip("Set RUN_LIVE_AI_EVAL=1 to call OpenAI with a synthetic form")
        assert os.getenv("MODEL_PROVIDER_API_KEY"), "Set MODEL_PROVIDER_API_KEY for the live eval"
    else:

        def complete(**kwargs):
            prompt = kwargs["messages"][-1]["content"]
            calls.append(prompt)
            assert "First name" in prompt
            assert "Text1" in prompt
            assert "SyntheticAlex" not in prompt
            response = {
                "fields": {
                    "Text1": {
                        "semantic_meaning": "first_name",
                        "expected_data_type": "string",
                        "confidence_score": 0.95,
                    }
                }
            }
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(response)))]
            )

        sdk_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
        monkeypatch.setenv("MODEL_PROVIDER_API_KEY", "synthetic-key")
        monkeypatch.setattr(field_semantics.provider_sdk, "OpenAI", lambda **_: sdk_client)

    monkeypatch.setattr(config, "API_AUTH_ENABLED", False)
    reset_rate_limit_state()
    builder = FormBuilder().text("Text1", required=True)
    label = DecodedStreamObject()
    label.set_data(b"BT /Helv 12 Tf 100 730 Td (First name) Tj ET")
    page = builder.pages[0]
    page[NameObject("/Resources")] = builder.acro_form["/DR"]
    page[NameObject("/Contents")] = builder.writer._add_object(label)
    source = builder.save(tmp_path / "opaque.pdf")
    files = {"pdf_file": ("opaque.pdf", source.read_bytes(), "application/pdf")}
    data = {"user_data": json.dumps({"applicant": {"first_name": "SyntheticAlex"}, "city": "Sampletown"})}

    with TestClient(create_app()) as client:
        baseline = client.post("/preview", files=files, data=data)
        assert baseline.status_code == 200
        assert baseline.json()["missing_required"] == ["Text1"]

        preview = client.post("/preview", files=files, data={**data, "use_semantic_inference": "true"})
        assert preview.status_code == 200
        decisions = preview.json()["decisions"]
        assert len(decisions) == 1, "AI did not produce a mapping on the synthetic form"
        (proposal,) = decisions
        assert proposal["ai_assisted"] and not proposal["requires_review"]
        assert (proposal["field_name"], proposal["selected_key"]) == ("Text1", "applicant.first_name")

        reviewed_mapping = {proposal["field_name"]: proposal["selected_key"]}
        output = client.post(
            "/fill", files=files, data={**data, "field_mapping": json.dumps(reviewed_mapping)}
        )
        assert output.status_code == 200
        assert not output.headers["X-PDF-Fields-AI-Assisted"]
        fields = PdfReader(io.BytesIO(output.content)).get_fields()
        assert fields["Text1"]["/V"] == "SyntheticAlex"
        if provider == "stub":
            assert len(calls) == 1
