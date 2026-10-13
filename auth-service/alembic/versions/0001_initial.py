"""waggi auth schema baseline (consolidated)

Initial baseline for the auth schema:
- account_type (company/creator) enum on users
- username (nullable, unique, CITEXT): creators log in with email or username

Revision ID: 0001
Revises:
Create Date: 2026-10-06
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Extensions (on public; usable from any schema).
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
    op.execute('CREATE EXTENSION IF NOT EXISTS "citext"')

    op.execute("CREATE SCHEMA IF NOT EXISTS auth")

    # create_type=False: we call .create() explicitly above; without this the
    # create_table step would try to CREATE TYPE again ("already exists").
    account_type = postgresql.ENUM(
        "company",
        "creator",
        name="account_type",
        schema="auth",
        create_type=False,
    )
    account_type.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("email", postgresql.CITEXT(), nullable=False, unique=True),
        # creators log in with email OR username.
        sa.Column("username", postgresql.CITEXT(), nullable=True, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("phone", sa.String(32), nullable=True),
        sa.Column("account_type", account_type, nullable=False, server_default=sa.text("'company'")),
        # Nullable so future SSO-only users can exist without a password.
        sa.Column("password_hash", sa.String(255), nullable=True),
        # While True, NO login flow issues session tokens — each returns a
        # single-use setup token exchangeable only at POST /setup-password.
        sa.Column("must_set_password", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        # TOTP 2FA. `totp_secret` is stored encrypted at rest (Fernet).
        sa.Column("totp_secret", sa.Text(), nullable=True),
        sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        # Hashed (sha256) one-time backup codes; empty when none remaining.
        sa.Column(
            "totp_backup_codes_hashed",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "tokens_invalid_before",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="auth",
    )
    op.create_index("ix_auth_users_email", "users", ["email"], schema="auth")
    op.create_index("ix_auth_users_username", "users", ["username"], schema="auth")

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        # Token family: every rotation inherits the login's family_id; replaying
        # a token revoked BY ROTATION (replaced_by_id set) revokes the family.
        sa.Column("family_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("replaced_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema="auth",
    )
    op.create_index("ix_auth_refresh_tokens_user_id", "refresh_tokens", ["user_id"], schema="auth")
    op.create_index("ix_auth_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], schema="auth")
    op.create_index("ix_auth_refresh_tokens_family_id", "refresh_tokens", ["family_id"], schema="auth")

    op.create_table(
        "password_resets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(255), nullable=False, unique=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        schema="auth",
    )
    op.create_index("ix_auth_password_resets_user_id", "password_resets", ["user_id"], schema="auth")
    op.create_index("ix_auth_password_resets_token_hash", "password_resets", ["token_hash"], schema="auth")

    op.create_table(
        "user_sso_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_subject", sa.String(255), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("provider", "provider_subject", name="uq_user_sso_links_provider_subject"),
        schema="auth",
    )
    op.create_index("ix_auth_user_sso_links_user_id", "user_sso_links", ["user_id"], schema="auth")
    op.create_index(
        "ix_auth_user_sso_links_provider_subject",
        "user_sso_links",
        ["provider", "provider_subject"],
        unique=True,
        schema="auth",
    )

    op.create_table(
        "user_passkeys",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("auth.users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("credential_id", sa.Text(), nullable=False, unique=True),
        sa.Column("public_key", sa.LargeBinary(), nullable=False),
        sa.Column("sign_count", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column(
            "transports",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("nickname", sa.String(120), nullable=True),
        # Device metadata captured at registration (display-only).
        sa.Column("aaguid", sa.String(36), nullable=True),
        sa.Column("attachment", sa.String(16), nullable=True),
        sa.Column("backed_up", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        schema="auth",
    )
    op.create_index("ix_auth_user_passkeys_user_id", "user_passkeys", ["user_id"], schema="auth")
    op.create_index("ix_auth_user_passkeys_credential_id", "user_passkeys", ["credential_id"], unique=True, schema="auth")


def downgrade() -> None:
    op.drop_index("ix_auth_user_passkeys_credential_id", schema="auth")
    op.drop_index("ix_auth_user_passkeys_user_id", schema="auth")
    op.drop_table("user_passkeys", schema="auth")

    op.drop_index("ix_auth_user_sso_links_provider_subject", schema="auth")
    op.drop_index("ix_auth_user_sso_links_user_id", schema="auth")
    op.drop_table("user_sso_links", schema="auth")

    op.drop_index("ix_auth_password_resets_token_hash", schema="auth")
    op.drop_index("ix_auth_password_resets_user_id", schema="auth")
    op.drop_table("password_resets", schema="auth")

    op.drop_index("ix_auth_refresh_tokens_family_id", schema="auth")
    op.drop_index("ix_auth_refresh_tokens_token_hash", schema="auth")
    op.drop_index("ix_auth_refresh_tokens_user_id", schema="auth")
    op.drop_table("refresh_tokens", schema="auth")

    op.drop_index("ix_auth_users_username", schema="auth")
    op.drop_index("ix_auth_users_email", schema="auth")
    op.drop_table("users", schema="auth")
    op.execute("DROP TYPE IF EXISTS auth.account_type")
    op.execute("DROP SCHEMA IF EXISTS auth")
