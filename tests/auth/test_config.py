"""Tests for auth Settings: derived lists and the production config guard."""

from __future__ import annotations

import pytest

from waggi_auth.config import Settings, settings


def test_webauthn_origins_list_parses_and_strips() -> None:
    s = Settings(webauthn_origins="http://localhost:5173, http://localhost:4173 ,,")
    assert s.webauthn_origins_list == ["http://localhost:5173", "http://localhost:4173"]


def test_extra_rp_hosts_and_known_rp_hosts() -> None:
    s = Settings(webauthn_rp_id="localhost", webauthn_extra_rp_hosts="a.ngrok.dev, b.ngrok.dev")
    assert s.webauthn_extra_rp_hosts_list == ["a.ngrok.dev", "b.ngrok.dev"]
    assert s.known_rp_hosts() == ["localhost", "a.ngrok.dev", "b.ngrok.dev"]


def test_allowed_frontend_origins() -> None:
    s = Settings(
        cors_origins="http://localhost:5173,http://localhost:4173",
        frontend_url="http://localhost:5173/",
        webauthn_extra_rp_hosts="a.ngrok.dev",
    )
    origins = s.allowed_frontend_origins()
    assert "http://localhost:5173" in origins
    assert "http://localhost:4173" in origins
    assert "https://a.ngrok.dev" in origins


def test_prod_guard_rejects_default_mfa_secret() -> None:
    s = Settings(environment="prod", mfa_token_secret="dev-mfa-secret-change-me")
    with pytest.raises(RuntimeError, match="MFA_TOKEN_SECRET"):
        s.validate_for_environment()


def test_prod_guard_rejects_empty_mfa_secret() -> None:
    s = Settings(environment="prod", mfa_token_secret="")
    with pytest.raises(RuntimeError, match="MFA_TOKEN_SECRET"):
        s.validate_for_environment()


def test_prod_guard_rejects_missing_totp_key() -> None:
    s = Settings(environment="prod", totp_encryption_key="")
    with pytest.raises(RuntimeError, match="TOTP_ENCRYPTION_KEY"):
        s.validate_for_environment()


def test_prod_guard_lists_all_problems() -> None:
    s = Settings(environment="prod", totp_encryption_key="", mfa_token_secret="dev-mfa-secret-change-me")
    with pytest.raises(RuntimeError) as excinfo:
        s.validate_for_environment()
    assert "TOTP_ENCRYPTION_KEY" in str(excinfo.value)
    assert "MFA_TOKEN_SECRET" in str(excinfo.value)


def test_prod_guard_passes_with_real_secrets() -> None:
    s = Settings(environment="prod", totp_encryption_key="x" * 44, mfa_token_secret="real-secret")
    s.validate_for_environment()  # no raise


def test_dev_guard_is_noop() -> None:
    s = Settings(environment="dev", totp_encryption_key="", mfa_token_secret="dev-mfa-secret-change-me")
    s.validate_for_environment()  # no raise


def test_global_settings_is_dev() -> None:
    assert settings.environment == "dev"
    settings.validate_for_environment()  # no raise
