"""SQLAlchemy models for the `auth` schema.

This schema is shared with the admin service (which reads/writes `users`), but
is OWNED here — auth's Alembic migration creates all tables. Admin has no
migrations of its own.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base for auth-service models (search_path = 'auth')."""


class AccountType(StrEnum):
    company = "company"
    creator = "creator"


class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "auth"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(CITEXT, unique=True, index=True, nullable=False)
    # Creators log in with email OR username; unique, CITEXT (case-insensitive).
    username: Mapped[str | None] = mapped_column(CITEXT, unique=True, index=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    account_type: Mapped[AccountType] = mapped_column(
        Enum(AccountType, name="account_type"), nullable=False, default=AccountType.company
    )
    # Nullable so future SSO-only users can exist without a password.
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Set when the account is created with a temporary (admin-shared) password
    # or with NO password at all (SSO-first), and on admin password resets.
    # While True, NO login flow issues session tokens — each returns a
    # short-lived single-use setup token instead, exchangeable ONLY at
    # POST /setup-password (mirrors the MFA challenge pattern).
    must_set_password: Mapped[bool] = mapped_column(default=False, nullable=False, server_default=text("false"))
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    # TOTP 2FA. `totp_secret` is stored encrypted at rest (Fernet); enabled is a
    # separate flag so a generated-but-unverified secret is not yet active.
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NOTE: text("false") renders as a bare `false` literal in DDL —
    # func.text("false") would render a text() FUNCTION call, which Postgres
    # rejects as a boolean default (DatatypeMismatchError).
    totp_enabled: Mapped[bool] = mapped_column(default=False, nullable=False, server_default=text("false"))
    # Hashed (sha256) one-time backup codes; empty when none remaining.
    totp_backup_codes_hashed: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    # Any refresh token issued before this timestamp is rejected on refresh.
    tokens_invalid_before: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    refresh_tokens: Mapped[list[RefreshToken]] = relationship(back_populates="user", cascade="all, delete-orphan")
    password_resets: Mapped[list[PasswordReset]] = relationship(back_populates="user", cascade="all, delete-orphan")
    sso_links: Mapped[list[UserSsoLink]] = relationship(back_populates="user", cascade="all, delete-orphan")
    passkeys: Mapped[list[UserPasskey]] = relationship(back_populates="user", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.email} ({self.account_type.value})>"


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = {"schema": "auth"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # L7 reuse detection: every rotation of a login's refresh token inherits
    # the same family_id (a fresh login starts a new family). replaced_by_id is
    # set ONLY when revocation happened via rotation — it distinguishes a
    # replayed-rotated-token (theft signal -> revoke the whole family) from a
    # replayed logged-out token (stale client -> benign 401).
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, default=uuid.uuid4, index=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="refresh_tokens")


class PasswordReset(Base):
    """Stores email-reset tokens. Defined now; used once email sending is enabled."""

    __tablename__ = "password_resets"
    __table_args__ = {"schema": "auth"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="password_resets")


class UserSsoLink(Base):
    """A linked external identity for a user (one user may have many).

    Decoupled from `users` columns so a user can sign in with multiple SSO
    providers (and/or a password). (provider, provider_subject) is globally
    unique: one external identity maps to exactly one user.
    """

    __tablename__ = "user_sso_links"
    __table_args__ = (
        UniqueConstraint("provider", "provider_subject", name="uq_user_sso_links_provider_subject"),
        {"schema": "auth"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    provider_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped[User] = relationship(back_populates="sso_links")


class UserPasskey(Base):
    """A registered WebAuthn passkey for passwordless login.

    Schema + models are in place now; the registration/authentication ceremony
    is deferred to a later round.
    """

    __tablename__ = "user_passkeys"
    __table_args__ = {"schema": "auth"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("auth.users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    credential_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    transports: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, server_default="{}")
    # Device metadata captured at registration (display-only, best-effort):
    # - aaguid identifies the authenticator (iCloud Keychain, 1Password, ...);
    #   many providers include it even with attestation "none". NULL = unknown.
    # - attachment: "platform" (built into the device) or "cross-platform"
    #   (security key / phone), as reported by the browser. NULL = not reported.
    # - backed_up: the WebAuthn BS flag — True for synced passkeys.
    aaguid: Mapped[str | None] = mapped_column(String(36), nullable=True)
    attachment: Mapped[str | None] = mapped_column(String(16), nullable=True)
    backed_up: Mapped[bool] = mapped_column(default=False, nullable=False, server_default=text("false"))
    nickname: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="passkeys")


__all__ = [
    "AccountType",
    "Base",
    "PasswordReset",
    "RefreshToken",
    "User",
    "UserPasskey",
    "UserSsoLink",
]
