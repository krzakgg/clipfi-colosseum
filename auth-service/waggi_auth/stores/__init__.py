"""Redis-backed ephemeral stores for the auth service.

Each module owns its keys, serialization and TTLs; connection lifecycle is
owned by `waggi_shared.redis` (per-URL singleton client). Everything here is
short-lived ceremony state:

- `challenges` — WebAuthn ceremony challenges (register/login), single-use.
- `mfa`        — single-use gates for the MFA login step (jti + TOTP codes).
- `sso_states` — OAuth login flow state + one-time login handles.
"""
