"""
Validated configuration for the service and library.

Configuration used to be read with bare ``os.getenv`` into module globals at
import time. That made settings untestable without reimporting modules, and a
typo in a numeric variable raised ``ValueError`` mid-import with a traceback
instead of a readable config error.

Everything now lives on one validated model built from the environment once at
startup. This is deliberately a plain pydantic ``BaseModel`` rather than
``pydantic-settings`` so the package keeps its zero-extra-dependency runtime
surface; ``Settings.from_env`` does the small amount of parsing that buys.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator


class ConfigurationError(RuntimeError):
    """Raised when the environment cannot be parsed into valid settings."""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number, got {raw!r}") from exc


def _env_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [item.strip() for item in raw.split(",") if item.strip()]


class Settings(BaseModel):
    """Runtime configuration for the API and pipeline."""

    model_config = {"frozen": True}

    # --- auth -------------------------------------------------------------
    auth_enabled: bool = True
    api_token: str = ""
    api_key_header: str = "X-API-Key"

    # --- limits -----------------------------------------------------------
    max_upload_bytes: int = Field(default=5 * 1024 * 1024, gt=0)
    max_user_data_bytes: int = Field(default=256 * 1024, gt=0)
    max_user_data_keys: int = Field(default=500, gt=0)
    max_user_data_depth: int = Field(default=8, gt=0)
    max_pdf_pages: int = Field(default=200, gt=0)
    max_pdf_text_chars: int = Field(default=2_000_000, gt=0)
    pdf_read_timeout_seconds: float = Field(default=20.0, gt=0)

    # --- rate limiting ----------------------------------------------------
    rate_limit_per_minute: int = Field(default=60, ge=0)
    trust_proxy_headers: bool = False

    # --- provider ---------------------------------------------------------
    provider_api_key: Optional[str] = None
    provider_model: str = "gpt-4o-mini"
    provider_timeout_seconds: float = Field(default=30.0, gt=0)
    provider_max_retries: int = Field(default=2, ge=0)
    provider_batch_size: int = Field(default=40, gt=0)

    # --- storage ----------------------------------------------------------
    state_dir: Path = Field(default_factory=lambda: Path.home() / ".pdf-autofiller")
    aliases_dir: Optional[Path] = None
    semantics_cache_size: int = Field(default=128, ge=0)

    # --- http -------------------------------------------------------------
    cors_allow_origins: list[str] = Field(default_factory=list)
    log_level: str = "INFO"

    @field_validator("log_level")
    @classmethod
    def _upper_log_level(cls, value: str) -> str:
        return value.upper()

    @property
    def templates_dir(self) -> Path:
        return self.state_dir / "templates"

    @property
    def profiles_dir(self) -> Path:
        return self.state_dir / "profiles"

    def auth_configured(self) -> bool:
        """True when a usable token is configured."""
        return bool(self.api_token)

    def token_matches(self, presented: Optional[str]) -> bool:
        """Constant-time comparison of a presented token against the configured one."""
        if not presented or not self.api_token:
            return False
        return secrets.compare_digest(presented, self.api_token)

    @classmethod
    def from_env(cls) -> "Settings":
        """Build settings from environment variables, raising on bad input."""
        aliases_env = os.getenv("FORM_ALIASES_DIR", "").strip()
        state_env = os.getenv("PDF_AUTOFILLER_STATE_DIR", "").strip()

        raw: dict[str, Any] = {
            "auth_enabled": _env_bool("API_AUTH_ENABLED", True),
            "api_token": os.getenv("API_AUTH_TOKEN", "").strip(),
            "api_key_header": os.getenv("API_KEY_HEADER", "X-API-Key"),
            "max_upload_bytes": _env_int("MAX_UPLOAD_BYTES", 5 * 1024 * 1024),
            "max_user_data_bytes": _env_int("MAX_USER_DATA_BYTES", 256 * 1024),
            "max_user_data_keys": _env_int("MAX_USER_DATA_KEYS", 500),
            "max_user_data_depth": _env_int("MAX_USER_DATA_DEPTH", 8),
            "max_pdf_pages": _env_int("MAX_PDF_PAGES", 200),
            "max_pdf_text_chars": _env_int("MAX_PDF_TEXT_CHARS", 2_000_000),
            "pdf_read_timeout_seconds": _env_float("PDF_READ_TIMEOUT_SECONDS", 20.0),
            "rate_limit_per_minute": _env_int("RATE_LIMIT_PER_MINUTE", 60),
            "trust_proxy_headers": _env_bool("TRUST_PROXY_HEADERS", False),
            "provider_api_key": os.getenv("MODEL_PROVIDER_API_KEY") or None,
            "provider_model": os.getenv("MODEL_PROVIDER_MODEL", "gpt-4o-mini"),
            "provider_timeout_seconds": _env_float("MODEL_PROVIDER_TIMEOUT_SECONDS", 30.0),
            "provider_max_retries": _env_int("MODEL_PROVIDER_MAX_RETRIES", 2),
            "provider_batch_size": _env_int("MODEL_PROVIDER_BATCH_SIZE", 40),
            "semantics_cache_size": _env_int("SEMANTICS_CACHE_SIZE", 128),
            "cors_allow_origins": _env_list("CORS_ALLOW_ORIGINS"),
            "log_level": os.getenv("LOG_LEVEL", "INFO"),
        }
        if aliases_env:
            raw["aliases_dir"] = Path(aliases_env).expanduser()
        if state_env:
            raw["state_dir"] = Path(state_env).expanduser()

        try:
            return cls(**raw)
        except ValidationError as exc:
            raise ConfigurationError(f"Invalid configuration: {exc}") from exc


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Return the process-wide settings, building them on first use."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


def set_settings(settings: Optional[Settings]) -> None:
    """Override (or with None, reset) the process-wide settings. Used by tests."""
    global _settings
    _settings = settings
