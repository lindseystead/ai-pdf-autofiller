"""Durable template workspace and storage boundary tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pdf_autofiller.api import config
from pdf_autofiller.api.app import create_app
from pdf_autofiller.api.security import reset_rate_limit_state
from pdf_autofiller.template_store import (
    LocalObjectStore,
    TemplateStateError,
    TemplateStore,
)

SAMPLE = Path("samples/sample_form.pdf")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(config, "PRODUCT_DATA_DIR", tmp_path / "product-data")
    monkeypatch.setattr(config, "API_AUTH_ENABLED", False)
    return TestClient(create_app())


def _create(client: TestClient) -> dict:
    response = client.post(
        "/v1/templates",
        data={"name": "Client intake"},
        files={"pdf_file": ("intake.pdf", SAMPLE.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_template_workspace_full_review_publish_fill_flow(client: TestClient) -> None:
    created = _create(client)
    assert created["status"] == "draft"
    assert created["revision"] == 1
    assert created["source_sha256"]
    assert created["mapping"]["txtFirstName"] == "first_name"

    before_publish = client.post(
        f"/v1/templates/{created['id']}/fills",
        json={"data": {"first_name": "Jane"}},
    )
    assert before_publish.status_code == 409
    assert before_publish.json()["detail"]["error"]["code"] == "template_not_published"

    mapping = dict(created["mapping"])
    mapping["txtEmail"] = "contact.email"
    updated = client.put(
        f"/v1/templates/{created['id']}/mapping",
        json={"expected_revision": 1, "mapping": mapping},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 2
    corrections = client.get(f"/v1/templates/{created['id']}/corrections")
    assert corrections.status_code == 200
    assert [
        {
            "field_name": item["field_name"],
            "suggested_key": item["suggested_key"],
            "approved_key": item["approved_key"],
        }
        for item in corrections.json()
    ] == [
        {
            "field_name": "txtEmail",
            "suggested_key": "email_address",
            "approved_key": "contact.email",
        }
    ]
    assert all("value" not in item for item in corrections.json())

    published = client.post(
        f"/v1/templates/{created['id']}/publish",
        json={"expected_revision": 2},
    )
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    filled = client.post(
        f"/v1/templates/{created['id']}/fills",
        json={
            "data": {
                "first_name": "Jane",
                "last_name": "Doe",
                "date_of_birth": "2000-01-01",
                "contact": {"email": "jane@example.test"},
                "phone_number": "2505550100",
            }
        },
    )
    assert filled.status_code == 201, filled.text
    job = filled.json()
    assert job["status"] == "completed"
    assert job["report"]["written_fields"] == [
        "txtDOB",
        "txtEmail",
        "txtFirstName",
        "txtLastName",
        "txtPhone",
    ]
    assert job["artifact_url"]

    artifact = client.get(job["artifact_url"])
    assert artifact.status_code == 200
    assert artifact.headers["content-type"] == "application/pdf"
    assert artifact.content.startswith(b"%PDF-")

    stored_job = client.get(f"/v1/jobs/{job['id']}")
    assert stored_job.status_code == 200
    assert stored_job.json() == job


def test_mapping_update_uses_optimistic_revision(client: TestClient) -> None:
    created = _create(client)
    first = client.put(
        f"/v1/templates/{created['id']}/mapping",
        json={"expected_revision": 1, "mapping": created["mapping"]},
    )
    assert first.status_code == 200

    stale = client.put(
        f"/v1/templates/{created['id']}/mapping",
        json={"expected_revision": 1, "mapping": created["mapping"]},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["error"]["code"] == "template_revision_conflict"


def test_replacement_pdf_creates_new_draft_without_changing_published_fill(client: TestClient) -> None:
    created = _create(client)
    blocked = client.post(
        f"/v1/templates/{created['id']}/versions",
        files={"pdf_file": ("replacement.pdf", SAMPLE.read_bytes(), "application/pdf")},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["error"]["code"] == "template_draft_exists"

    published = client.post(
        f"/v1/templates/{created['id']}/publish",
        json={"expected_revision": 1},
    )
    assert published.status_code == 200

    replacement = client.post(
        f"/v1/templates/{created['id']}/versions",
        files={"pdf_file": ("replacement.pdf", SAMPLE.read_bytes(), "application/pdf")},
    )
    assert replacement.status_code == 201, replacement.text
    assert replacement.json()["version"] == 2
    assert replacement.json()["status"] == "draft"

    # Filling continues to use the most recent published version until v2 is reviewed.
    filled = client.post(
        f"/v1/templates/{created['id']}/fills",
        json={
            "data": {
                "first_name": "Jane",
                "last_name": "Doe",
                "date_of_birth": "2000-01-01",
            }
        },
    )
    assert filled.status_code == 201, filled.text
    assert filled.json()["template_version"] == 1


def test_mapping_rejects_unknown_and_publish_rejects_missing_required_fields(client: TestClient) -> None:
    created = _create(client)
    unknown = client.put(
        f"/v1/templates/{created['id']}/mapping",
        json={"expected_revision": 1, "mapping": {**created["mapping"], "not-a-field": "value"}},
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["error"]["details"]["unknown_fields"] == ["not-a-field"]

    incomplete = dict(created["mapping"])
    incomplete.pop("txtFirstName")
    missing = client.put(
        f"/v1/templates/{created['id']}/mapping",
        json={"expected_revision": 1, "mapping": incomplete},
    )
    assert missing.status_code == 200
    publish = client.post(
        f"/v1/templates/{created['id']}/publish",
        json={"expected_revision": 2},
    )
    assert publish.status_code == 422
    assert publish.json()["detail"]["error"]["details"]["missing_required_fields"] == ["txtFirstName"]


def test_template_listing_and_source_are_authenticated_api_surfaces(client: TestClient) -> None:
    created = _create(client)
    listing = client.get("/v1/templates")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()] == [created["id"]]

    details = client.get(f"/v1/templates/{created['id']}")
    assert details.status_code == 200
    source = client.get(created["source_url"])
    assert source.status_code == 200
    assert source.content == SAMPLE.read_bytes()


def test_workspace_upload_is_rejected_before_parsing_without_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "PRODUCT_DATA_DIR", tmp_path / "protected-data")
    monkeypatch.setattr(config, "API_AUTH_ENABLED", True)
    monkeypatch.setattr(config, "API_AUTH_TOKEN", "correct-token")
    protected = TestClient(create_app())
    response = protected.post(
        "/v1/templates",
        data={"name": "Private"},
        files={"pdf_file": ("private.pdf", SAMPLE.read_bytes(), "application/pdf")},
    )
    assert response.status_code == 401
    assert not (tmp_path / "protected-data").exists()


def test_json_product_mutation_is_bounded_before_parsing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create(client)
    monkeypatch.setattr(config, "JSON_BODY_MAX_BYTES", 32)
    response = client.post(
        f"/v1/templates/{created['id']}/publish",
        content=b"{" + (b'"padding":"' + b"x" * 100 + b'"}'),
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["error"]["details"]["max_body_bytes"] == 32


def test_json_product_mutation_is_not_rate_limited_twice(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = _create(client)
    monkeypatch.setattr(config, "RATE_LIMIT_PER_MINUTE", 1)
    reset_rate_limit_state()
    response = client.post(
        f"/v1/templates/{created['id']}/publish",
        json={"expected_revision": 1},
    )
    assert response.status_code == 200, response.text


def test_fill_values_are_not_written_to_metadata_database(client: TestClient, tmp_path: Path) -> None:
    # The client fixture's data path is under this test's tmp_path.
    created = _create(client)
    published = client.post(
        f"/v1/templates/{created['id']}/publish",
        json={"expected_revision": 1},
    )
    assert published.status_code == 200
    secret = "VALUE-MUST-NOT-BE-IN-METADATA-9f7c"
    filled = client.post(
        f"/v1/templates/{created['id']}/fills",
        json={
            "data": {
                "first_name": secret,
                "last_name": "Doe",
                "date_of_birth": "2000-01-01",
            }
        },
    )
    assert filled.status_code == 201
    metadata_files = list((tmp_path / "product-data").glob("metadata.sqlite3*"))
    assert metadata_files
    assert all(secret.encode() not in path.read_bytes() for path in metadata_files)


def test_local_object_store_rejects_path_traversal(tmp_path: Path) -> None:
    objects = LocalObjectStore(tmp_path)
    with pytest.raises(ValueError, match="Invalid object key"):
        objects.resolve("sources/../metadata.sqlite3")
    with pytest.raises(ValueError, match="Invalid object key"):
        objects.resolve("other/file.pdf")


def test_repository_freezes_published_mapping(tmp_path: Path) -> None:
    store = TemplateStore(tmp_path)
    key, digest = store.objects.put_source(SAMPLE.read_bytes())
    template = {
        "example": {"first_name": ""},
        "required_keys": ["first_name"],
        "fields": [
            {
                "field_name": "txtFirstName",
                "key": "first_name",
                "required": True,
                "field_type": "text",
            }
        ],
    }
    created = store.repository.create_template(
        name="Frozen",
        source_sha256=digest,
        source_key=key,
        template=template,
        mapping={"txtFirstName": "first_name"},
    )
    store.repository.publish(created.template_id, expected_revision=1)

    with pytest.raises(TemplateStateError, match="already published"):
        store.repository.update_mapping(
            created.template_id,
            mapping={"txtFirstName": "other"},
            expected_revision=1,
        )
