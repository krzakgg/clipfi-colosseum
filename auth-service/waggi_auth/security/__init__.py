"""Auth-side security primitives, split by concern.

- `keys`   — RSA signing keypair lifecycle (load/generate/persist) + the JWKS
  document exposed at `/.well-known/jwks.json`.
- `signing` — token creation/verification (RS256 access, opaque refresh,
  short-lived HS256 MFA challenge).
- `totp`   — TOTP 2FA helpers: secret encryption at rest (Fernet), code
  verification, backup-code generation/hashing.

Auth is the *issuing* side. Verification used by admin/bookings lives in
`waggi_shared.security`.
"""
