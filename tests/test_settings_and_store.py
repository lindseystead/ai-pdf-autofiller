"""Tests for validated settings and the template/profile store."""

from __future__ import annotations

import time

import pytest

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


def test_unreadable_entries_are_skipped_not_fatal():
    store = template_store()
    store.save(Template(name="good", fingerprint="f"))
    (store.directory / "broken.json").write_text("{not json", encoding="utf-8")
    assert [t.name for t in store.list()] == ["good"]


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


def test_bad_numeric_env_raises_configuration_error(monkeypatch):
    """A typo in config should be a readable error, not a traceback at import."""
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "not-a-number")
    with pytest.raises(ConfigurationError) as exc:
        Settings.from_env()
    assert "MAX_UPLOAD_BYTES" in str(exc.value)


def test_token_comparison_rejects_wrong_and_empty_values():
    settings = Settings(auth_enabled=True, api_token="secret")
    assert settings.auth_configured() is True
    assert settings.token_matches("secret") is True
    assert settings.token_matches("wrong") is False
    assert settings.token_matches(None) is False
    assert Settings(auth_enabled=True).auth_configured() is False


def test_negative_limits_are_rejected():
    with pytest.raises(Exception):
        Settings(max_upload_bytes=-1)
