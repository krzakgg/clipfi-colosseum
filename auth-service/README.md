# waggi auth-service

Identity service for waggi. Single source of truth for users, credentials, and
tokens:

- **Single `users` table with `account_type`** (`company` | `creator`). The
  main backend will link `companies`/`creators` rows to `users.id` (follow-up
  task).
- **Login by email OR username** (creators register a username).
- **Public self-signup** — `POST /api/v1/auth/register` (rate-limited per IP,
  full password policy). waggi's frontend registers accounts itself.

## Responsibilities

- Users directory (email, username, full_name, phone [E.164], account_type) — `auth` schema
- argon2id password hashing + timing-equalized rejects on unknown emails;
  outdated hashes transparently re-hashed on successful login
- Password policy: no personal tokens (email local part / name words) AND min
  length (env-configurable, default 8; max fixed 64) AND character-class
  minimums. Active policy published via public `GET /api/v1/auth/password-policy`
- RS256 JWT access tokens + rotating refresh tokens (atomic single-use
  rotation, family-wide revocation on reuse detection)
- `tokens_invalid_before` per user → revokes all refresh tokens on password change/reset
- JWKS endpoint (`/.well-known/jwks.json`) — public trust root for other services
- MFA: TOTP + one-time backup codes; MFA challenge tokens single-use (Redis)
- Password reset (self; email flow ships LoggingEmailSender) and forced
  password setup (`must_set_password`)
- Rate limiting (Redis, via `limits`): login 10/min/email + 30/min/IP, MFA
  step 10/min/IP, 2FA verify/disable 10/min/user, reset request 5/h/email +
  20/h/IP, register 20/h/IP — fails open if Redis is down
- Passkeys (WebAuthn): registration + usernameless login; challenges in Redis
- SSO (Google / Apple): OAuth authorization-code flow; identities in
  `auth.user_sso_links`

## Layout

```
waggi_auth/
  config.py  models.py  dependencies.py  rate_limit.py  tokens.py  main.py
  providers/          # Google/Apple OAuth clients
  security/           # keys (RSA+JWKS) · signing (access/refresh/MFA tokens) · totp
  stores/             # Redis-backed: challenges · mfa · sso_states
  schemas/            # Pydantic models by domain, re-exported from __init__
  routers/            # session (login/register/refresh/logout) · profile · password · mfa · passkeys · sso · jwks
waggi_shared/         # vendored cross-cutting lib (errors, redis, passwords, policy, ...)
alembic/              # migrations (auth schema)
```

## Run (Docker)

```bash
cp .env.example .env       # fill AUTH_POSTGRES_PASSWORD / AUTH_REDIS_PASSWORD etc.
python scripts/generate_keys.py
cd .. && docker compose up -d auth-postgres auth-redis auth-migrate auth-api
```

Or from the repo root (root compose includes this file):

```bash
docker compose up -d
```

The API joins the `jestr-services` network as `auth-api:8001` (other services
call it there) and is published locally on `127.0.0.1:8001`.

## Run (bare metal)

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e .
python scripts/generate_keys.py
alembic upgrade head
uvicorn waggi_auth.main:app --reload --port 8001
```

Requires a local Postgres (`waggi_auth` DB) and Redis. Generate the JWT
keypair with `scripts/generate_keys.py`; `keys/` is gitignored.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql://...localhost:5432/waggi_auth` | Postgres (auth schema) |
| `REDIS_URL` | `redis://localhost:6379/0` | Challenges, SSO state, rate limits |
| `JWT_PRIVATE_KEY_PATH` / `JWT_PUBLIC_KEY_PATH` | `./keys/*.pem` | RS256 signing keypair |
| `JWT_KEY_ID` / `JWT_ISSUER` | `waggi-auth-1` / `waggi-auth` | JWT header kid + issuer |
| `TOTP_ENCRYPTION_KEY` | *(empty; required in prod)* | Fernet key for TOTP secrets at rest |
| `MFA_TOKEN_SECRET` | *(dev default; required in prod)* | HS256 secret for MFA/setup tokens |
| `CORS_ORIGINS` / `FRONTEND_URL` | `http://localhost:5173` | SPA origins |
| `WEBAUTHN_RP_ID` / `WEBAUTHN_ORIGINS` | `localhost` / `:5173,:4173` | Passkey relying party |
| `GOOGLE_*` / `APPLE_*` | *(empty = disabled)* | SSO providers |

## SSO setup

Redirect URIs follow
`<API origin>/api/v1/auth/sso/{google,apple}/callback`. Providers stay
disabled until their credentials are configured; the frontend discovers the
enabled set via `GET /api/v1/auth/sso/providers`.

## Tests

`tests/auth/` at the repo root (run from the repo root against a real local
Postgres; `waggi_auth_test` is created automatically):

```bash
pip install -r requirements-dev.txt
pytest tests/auth
```
