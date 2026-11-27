"""Exercise the real preview-to-fill contract with synthetic AcroForms."""

import io
import json
import os
import socket
import threading
import time
from types import SimpleNamespace

import pytest
import uvicorn
from fastapi.testclient import TestClient
from pypdf import PdfReader
from pypdf.generic import DecodedStreamObject, NameObject

from pdf_autofiller import field_semantics
from pdf_autofiller.api import config
from pdf_autofiller.api.app import create_app
from pdf_autofiller.api.security import reset_rate_limit_state

from .form_factory import FormBuilder


@pytest.fixture
def provider_stub(monkeypatch):
    calls = []
    state = {"behavior": "success"}

    def complete(**kwargs):
        prompt = kwargs["messages"][-1]["content"]
        calls.append(prompt)
        assert "First name" in prompt
        assert "Text1" in prompt
        assert "SyntheticAlex" not in prompt
        if state["behavior"] == "timeout":
            raise TimeoutError("Synthetic provider timeout")
        if state["behavior"] == "malformed":
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{"))])
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
    return calls, state


@pytest.fixture
def synthetic_form(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "API_AUTH_ENABLED", False)
    reset_rate_limit_state()
    builder = FormBuilder().text("Text1", required=True)
    label = DecodedStreamObject()
    label.set_data(b"BT /Helv 12 Tf 100 730 Td (First name) Tj ET")
    page = builder.pages[0]
    page[NameObject("/Resources")] = builder.acro_form["/DR"]
    page[NameObject("/Contents")] = builder.writer._add_object(label)
    return builder.save(tmp_path / "opaque.pdf")


@pytest.mark.parametrize("provider", ["stub", "live", "timeout", "malformed"])
def test_ai_preview_review_and_fill(provider, synthetic_form, request):
    if provider == "live":
        if os.getenv("RUN_LIVE_AI_EVAL") != "1":
            pytest.skip("Set RUN_LIVE_AI_EVAL=1 to call OpenAI with a synthetic form")
        assert os.getenv("MODEL_PROVIDER_API_KEY"), "Set MODEL_PROVIDER_API_KEY for the live eval"
    else:
        calls, state = request.getfixturevalue("provider_stub")
        if provider in {"timeout", "malformed"}:
            state["behavior"] = provider
    source = synthetic_form
    files = {"pdf_file": ("opaque.pdf", source.read_bytes(), "application/pdf")}
    data = {"user_data": json.dumps({"applicant": {"first_name": "SyntheticAlex"}, "city": "Sampletown"})}

    with TestClient(create_app()) as client:
        baseline = client.post("/preview", files=files, data=data)
        assert baseline.status_code == 200
        assert baseline.json()["missing_required"] == ["Text1"]

        preview = client.post("/preview", files=files, data={**data, "use_semantic_inference": "true"})
        assert preview.status_code == 200
        decisions = preview.json()["decisions"]
        if provider in {"timeout", "malformed"}:
            assert decisions == []
            assert preview.json()["missing_required"] == ["Text1"]
            blocked = client.post("/fill", files=files, data=data)
            assert blocked.status_code == 422
            reviewed_mapping = {"Text1": "applicant.first_name"}
        else:
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
        if provider != "live":
            assert len(calls) == 1


def test_browser_ai_review_and_download(synthetic_form, request):
    if os.getenv("RUN_BROWSER_E2E") != "1":
        pytest.skip("Set RUN_BROWSER_E2E=1 after installing Playwright and Chromium")
    from playwright.sync_api import expect, sync_playwright

    calls, state = request.getfixturevalue("provider_stub")
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.02)
            assert server.started
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                page = browser.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{port}/playground")
                page.locator("#file").set_input_files(synthetic_form)
                data = page.locator("#userData")
                data.fill('{"applicant":{"first_name":"SyntheticAlex"}}')
                page.locator("#aiConsent").check()
                page.locator("#semantic").check()
                proposal = page.get_by_role("button", name="Accept Text1 ← applicant.first_name")

                state["behavior"] = "timeout"
                page.locator("#previewBtn").click()
                expect(page.locator("#status")).to_contain_text("No AI suggestions")
                expect(proposal).to_be_hidden()

                state["behavior"] = "success"
                page.locator("#previewBtn").click()
                expect(proposal).to_be_visible()
                data.fill('{"applicant":{"first_name":"ReviewedAlex"}}')
                expect(proposal).to_be_hidden()
                page.locator("#previewBtn").click()
                proposal.click()
                assert json.loads(page.locator("#fieldMapping").input_value()) == {
                    "Text1": "applicant.first_name"
                }
                page.locator("#fillBtn").click()
                with page.expect_download() as download:
                    page.locator("#download").click()
                assert PdfReader(download.value.path()).get_fields()["Text1"]["/V"] == "ReviewedAlex"
                assert len(calls) == 3
                assert not errors
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=5)
