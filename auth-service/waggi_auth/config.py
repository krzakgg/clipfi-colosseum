"""Auth service configuration.

Self-contained (does not subclass the shared BaseSettings) so that mypy strict
can see every field without the pydantic mypy plugin, which is currently broken
on this platform. All fields are env-driven via pydantic-settings.
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

from waggi_shared.password_policy import PasswordPolicyConfig


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False)

    # --- shared across services (env-driven) -----------------------------
    environment: Literal["dev", "prod"] = "dev"
    database_url: str = "postgresql+asyncpg://waggi_auth:waggi_auth@localhost:5432/waggi_auth"
    auth_service_url: str = "http://localhost:8001"
    jwt_issuer: str = "waggi-auth"
    jwks_url: str = "http://localhost:8001/.well-known/jwks.json"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 14
    cors_origins: str = "http://localhost:5173"

    # --- auth-specific ---------------------------------------------------
    # Auth is the ONLY service with the private key.
    jwt_private_key_path: str = "./keys/auth_private.pem"
    jwt_public_key_path: str = "./keys/auth_public.pem"
    jwt_key_id: str = "waggi-auth-1"
    password_reset_ttl_minutes: int = 30

    # --- Password policy (published via GET /auth/password-policy) --------
    # Minimums for every password the service sets (setup/change/reset).
    # Max length is NOT configurable — 64, hard-enforced by the request
    # schemas and the shared policy alike (NIST 800-63B floor).
    # Character-class minimums: uppercase/lowercase/digit default to 1
    # (symbol 0 — optional); all configurable via env, 0 disables a rule.
    password_min_length: int = 8
    password_min_uppercase: int = 1
    password_min_lowercase: int = 1
    password_min_digit: int = 1
    password_min_symbol: int = 0

    # --- TOTP 2FA --------------------------------------------------------
    # Fernet key (base64, 32 bytes) for encrypting TOTP secrets at rest.
    # Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    totp_encryption_key: str = ""
    # Short-lived HS256 token issued after password check when 2FA is required.
    mfa_token_secret: str = "dev-mfa-secret-change-me"
    mfa_token_ttl_minutes: int = 5
    # Setup token: issued by login flows while `must_set_password` is set,
    # exchangeable only at POST /setup-password. Signs with the same secret
    # as MFA tokens (the `aud` claim separates them); longer TTL because
    # the user is choosing a password, not reading a 6-digit code.
    setup_token_ttl_minutes: int = 15

    # --- WebAuthn (passkeys) ---------------------------------------------
    # Relying Party config for the WebAuthn ceremony. rp_id must equal the
    # host the frontend is served from (no port); origins list the exact
    # scheme://host:port values allowed for the ceremony.
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "Waggi"
    webauthn_origins: str = "http://localhost:5173,http://localhost:4173"
    # Additional serving hosts (e.g. an ngrok tunnel domain for phone testing).
    # Each host H is trusted as rp_id=H with origin https://H — resolved per
    # request from the Origin header, so localhost and tunnel flows coexist.
    # Set via scripts/ngrok.sh or manually: WEBAUTHN_EXTRA_RP_HOSTS=abc.ngrok-free-static.app
    webauthn_extra_rp_hosts: str = ""
    # Redis backs the WebAuthn challenge store (multi-worker safe: any worker
    # can finish a ceremony another worker started). Ephemeral by design.
    redis_url: str = "redis://localhost:6379/0"

    # --- SSO (Google / Apple) ---------------------------------------------
    # Frontend origin for OAuth redirects: authorize derives the RETURN url
    # from it (Origin header wins when it is a trusted host). The provider
    # redirect_uri (the callback) instead uses api_public_url when set.
    # Provider enablement lives in waggi_auth/providers/ (each provider module
    # knows which of its fields must be set).
    frontend_url: str = "http://localhost:5173"
    # Public origin of THIS API as the browser reaches it. Prod serves the
    # API on its own host (https://api.waggi.local) while the SPA sits on
    # app.waggi.local — the OAuth redirect_uri must land on the API host.
    # Empty (dev) falls back to the frontend origin (Vite same-origin proxy).
    api_public_url: str = ""
    # Google OAuth: https://console.cloud.google.com/apis/credentials
    # Redirect URI to register: <public API origin>/api/v1/auth/sso/google/callback
    # (prod: https://api.waggi.local/api/v1/auth/sso/google/callback)
    google_client_id: str = ""
    google_client_secret: str = ""
    # Sign in with Apple: needs a paid Apple Developer account.
    # Services ID (= client id) + team id + key id + the .p8 private key file.
    # Redirect URI to register: <public API origin>/api/v1/auth/sso/apple/callback
    # (prod: https://api.waggi.local/api/v1/auth/sso/apple/callback)
    apple_client_id: str = ""
    apple_team_id: str = ""
    apple_key_id: str = ""
    apple_private_key_path: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        """Comma-separated CORS_ORIGINS env var -> clean list of origins.

        Browser origins allowed to call the API cross-origin (prod: the SPA
        on app.waggi.local; the API itself lives on api.waggi.local).
        Feeds CORSMiddleware in main.py and the SSO redirect-trust list.
        """
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def webauthn_origins_list(self) -> list[str]:
        """Comma-separated WEBAUTHN_ORIGINS env var -> clean list of origins."""
        return [o.strip() for o in self.webauthn_origins.split(",") if o.strip()]

    @property
    def webauthn_extra_rp_hosts_list(self) -> list[str]:
        """Comma-separated WEBAUTHN_EXTRA_RP_HOSTS -> clean list of hosts."""
        return [h.strip() for h in self.webauthn_extra_rp_hosts.split(",") if h.strip()]

    def known_rp_hosts(self) -> list[str]:
        """All hosts allowed as WebAuthn rp_id (default + extras)."""
        return [self.webauthn_rp_id, *self.webauthn_extra_rp_hosts_list]

    def allowed_frontend_origins(self) -> list[str]:
        """Origins the SSO flow may redirect back to.

        The configured CORS origins plus every extra WebAuthn rp host (the
        ngrok tunnel domains serve the frontend over https). Same trust
        surface as `_resolve_rp` in the passkey router.
        """
        origins = list(self.cors_origins_list)
        if self.frontend_url:
            origins.append(self.frontend_url.rstrip("/"))
        origins.extend(f"https://{h}" for h in self.webauthn_extra_rp_hosts_list)
        return origins

    def validate_for_environment(self) -> None:
        """Fail fast on insecure configuration in production.

        Dev keeps working with generated/dev secrets; prod must not boot with
        the dev-default MFA signing secret or without the TOTP encryption key
        (empty key would crash at first use anyway — better at startup).
        """
        if self.environment != "prod":
            return
        problems: list[str] = []
        if not self.totp_encryption_key:
            problems.append("TOTP_ENCRYPTION_KEY is not set")
        if not self.mfa_token_secret or self.mfa_token_secret == "dev-mfa-secret-change-me":
            problems.append("MFA_TOKEN_SECRET is not set (or left at its dev default)")
        if problems:
            raise RuntimeError("Refusing to start with insecure config: " + "; ".join(problems))

    def validated_password_policy(self) -> PasswordPolicyConfig:
        """The assembled policy, with sanity checks applied.

        Raises RuntimeError on impossible configurations (min beyond the
        fixed max of 64, class minimums that no password could satisfy)
        so a bad env var fails loudly at first use instead of silently
        weakening the policy.
        """
        try:
            return PasswordPolicyConfig(
                min_length=self.password_min_length,
                min_uppercase=self.password_min_uppercase,
                min_lowercase=self.password_min_lowercase,
                min_digit=self.password_min_digit,
                min_symbol=self.password_min_symbol,
            )
        except ValueError as exc:
            raise RuntimeError(f"Invalid password policy config: {exc}") from exc


settings = Settings()
