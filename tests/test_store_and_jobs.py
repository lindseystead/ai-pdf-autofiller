"""Tests for template/profile storage, batch jobs, metrics, and settings."""

from __future__ import annotations

import time

import pytest

from pdf_autofiller import jobs, metrics
from pdf_autofiller.errors import ProfileNotFoundError, TemplateNotFoundError
from pdf_autofiller.settings import ConfigurationError, Settings, set_settings
from pdf_autofiller.store import (
    Profile,
    Template,
    profile_store,
    resolve_fill_inputs,
    sanitize_name,
    template_store,
)


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path):
    set_settings(Settings(state_dir=tmp_path, auth_enabled=False))
    yield
    set_settings(None)


# --- naming safety ---------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("w9", "w9"),
        ("My Form 2026", "My-Form-2026"),
        ("../../etc/passwd", "etc-passwd"),
        ("a/b\\c", "a-b-c"),
        ("...", None),
        ("", None),
    ],
)
def test_sanitize_name_cannot_escape_the_store(raw, expected):
    """Names arrive over HTTP and become filenames, so traversal must not survive."""
    if expected is None:
        with pytest.raises(ValueError):
            sanitize_name(raw)
    else:
        result = sanitize_name(raw)
        assert result == expected
        assert "/" not in result and ".." not in result


# --- stores ----------------------------------------------------------------


def test_template_round_trip():
    store = template_store()
    saved = store.save(
        Template(name="w9", fingerprint="abc123", overrides={"txtName": "Acme"}, flatten=True)
    )
    loaded = store.get("w9")
    assert loaded.overrides == {"txtName": "Acme"}
    assert loaded.flatten is True
    assert loaded.created_at == saved.created_at
    assert [t.name for t in store.list()] == ["w9"]
    store.delete("w9")
    with pytest.raises(TemplateNotFoundError):
        store.get("w9")


def test_saving_over_a_template_preserves_created_at():
    store = template_store()
    first = store.save(Template(name="t", fingerprint="f"))
    time.sleep(1.01)
    second = store.save(Template(name="t", fingerprint="f", description="updated"))
    assert second.created_at == first.created_at
    assert second.updated_at >= first.updated_at


def test_missing_entries_raise_typed_errors():
    with pytest.raises(TemplateNotFoundError) as exc:
        template_store().get("nope")
    assert exc.value.code == "template_not_found"
    assert exc.value.status_code == 404
    with pytest.raises(ProfileNotFoundError):
        profile_store().get("nope")


def test_unreadable_entries_are_skipped_not_fatal(tmp_path):
    store = template_store()
    store.save(Template(name="good", fingerprint="f"))
    store.directory.mkdir(parents=True, exist_ok=True)
    (store.directory / "broken.json").write_text("{not json", encoding="utf-8")
    assert [t.name for t in store.list()] == ["good"]


# --- precedence ------------------------------------------------------------


def test_request_data_layers_over_profile_and_overrides_win():
    """Least-to-most specific: profile < request data < template < request overrides."""
    profile_store().save(Profile(name="me", data={"firstname": "Jane", "city": "Boston"}))
    template_store().save(
        Template(name="t", fingerprint="f", overrides={"fld": "from-template"})
    )

    data, overrides, template = resolve_fill_inputs(
        template_name="t",
        profile_name="me",
        user_data={"city": "Cambridge"},
        overrides={"fld": "from-request"},
    )
    assert data == {"firstname": "Jane", "city": "Cambridge"}
    assert overrides == {"fld": "from-request"}
    assert template is not None and template.name == "t"


def test_template_key_alias_reads_from_resolved_data():
    profile_store().save(Profile(name="me", data={"legal_name": "Jane Q Doe"}))
    template_store().save(
        Template(name="t", fingerprint="f", key_aliases={"txtFullName": "legal_name"})
    )
    _, overrides, _ = resolve_fill_inputs(template_name="t", profile_name="me")
    assert overrides == {"txtFullName": "Jane Q Doe"}


# --- jobs ------------------------------------------------------------------


def _wait_for_completion(job_id: str, timeout: float = 10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = jobs.get_job(job_id)
        if job and job.status == "completed":
            return job
        time.sleep(0.02)
    raise AssertionError("batch job did not complete in time")


def test_batch_records_per_item_outcomes():
    items = [{"name": "a"}, {"name": "b"}, {"name": "c"}]

    def worker(item):
        if item["name"] == "b":
            raise ValueError("bad row")
        return {"output_path": f"/tmp/{item['name']}.pdf", "fields_written": 3}

    job = jobs.submit_batch(items, worker)
    done = _wait_for_completion(job.job_id)

    assert done.total == 3
    assert done.succeeded == 2
    assert done.failed == 1
    # One bad row must not discard the others.
    statuses = {item.name: item.status for item in done.items}
    assert statuses == {"a": "succeeded", "b": "failed", "c": "succeeded"}
    failed = next(i for i in done.items if i.name == "b")
    assert failed.error_message == "bad row"
    # The API must not imply durability it does not have.
    assert done.durable is False


def test_unknown_job_returns_none():
    assert jobs.get_job("does-not-exist") is None


# --- metrics ---------------------------------------------------------------


def test_metrics_render_prometheus_format():
    metrics.reset()
    metrics.increment("pdf_autofiller_fills_total", outcome="success")
    metrics.increment("pdf_autofiller_fills_total", 2, outcome="success")
    metrics.observe("pdf_autofiller_request_duration_seconds", 0.3, endpoint="/v1/fill")

    output = metrics.render()
    assert '# TYPE pdf_autofiller_fills_total counter' in output
    assert 'pdf_autofiller_fills_total{outcome="success"} 3' in output
    assert 'pdf_autofiller_request_duration_seconds_bucket{endpoint="/v1/fill",le="0.5"} 1' in output
    assert 'pdf_autofiller_request_duration_seconds_count{endpoint="/v1/fill"} 1' in output
    metrics.reset()


def test_metrics_escape_label_values():
    metrics.reset()
    metrics.increment("pdf_autofiller_fills_total", outcome='we"ird\\path')
    assert 'we\\"ird\\\\path' in metrics.render()
    metrics.reset()


# --- settings --------------------------------------------------------------


def test_bad_numeric_env_raises_configuration_error(monkeypatch):
    """A typo in config should be a readable error, not a traceback at import."""
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "not-a-number")
    with pytest.raises(ConfigurationError) as exc:
        Settings.from_env()
    assert "MAX_UPLOAD_BYTES" in str(exc.value)


def test_multi_key_auth_resolves_key_names(monkeypatch):
    monkeypatch.setenv("API_KEYS", "ops:secret-one,ci:secret-two")
    monkeypatch.delenv("API_AUTH_TOKEN", raising=False)
    settings = Settings.from_env()
    assert settings.resolve_key("secret-one") == "ops"
    assert settings.resolve_key("secret-two") == "ci"
    assert settings.resolve_key("wrong") is None
    assert settings.resolve_key(None) is None


def test_negative_limits_are_rejected():
    with pytest.raises(Exception):
        Settings(max_upload_bytes=-1)
