"""Pydantic request/response schemas for the auth API, split by domain.

Re-exported here so consumers can keep importing `from waggi_auth.schemas
import X` regardless of which domain module defines it.
"""

from __future__ import annotations

from waggi_auth.schemas.common import MessageResponse
from waggi_auth.schemas.mfa import (
    TotpBackupCodesResponse,
    TotpDisableRequest,
    TotpRegenerateRequest,
    TotpSetupRequest,
    TotpSetupResponse,
    TotpStatusResponse,
    TotpVerifyRequest,
)
from waggi_auth.schemas.passkeys import (
    PasskeyBeginResponse,
    PasskeyLoginFinishRequest,
    PasskeyOut,
    PasskeyRegisterFinishRequest,
    PasskeyRenameRequest,
)
from waggi_auth.schemas.password import (
    ChangePasswordRequest,
    PasswordPolicyOut,
    PasswordResetConfirm,
    PasswordResetRequest,
    SetupPasswordRequest,
)
from waggi_auth.schemas.session import (
    LoginMfaRequest,
    LoginRequest,
    MfaRequiredResponse,
    RefreshRequest,
    SetupRequiredResponse,
    TokenResponse,
)
from waggi_auth.schemas.sso import (
    SsoAuthorizeRequest,
    SsoAuthorizeResponse,
    SsoCompleteRequest,
    SsoLinkOut,
    SsoProviderOut,
)
from waggi_auth.schemas.users import RegisterRequest, UpdateMeRequest, UserOut

__all__ = [
    "ChangePasswordRequest",
    "LoginMfaRequest",
    "LoginRequest",
    "MessageResponse",
    "MfaRequiredResponse",
    "PasskeyBeginResponse",
    "PasskeyLoginFinishRequest",
    "PasskeyOut",
    "PasskeyRegisterFinishRequest",
    "PasskeyRenameRequest",
    "PasswordPolicyOut",
    "PasswordResetConfirm",
    "PasswordResetRequest",
    "RefreshRequest",
    "SetupPasswordRequest",
    "SetupRequiredResponse",
    "SsoAuthorizeRequest",
    "SsoAuthorizeResponse",
    "SsoCompleteRequest",
    "SsoLinkOut",
    "SsoProviderOut",
    "TokenResponse",
    "TotpBackupCodesResponse",
    "TotpDisableRequest",
    "TotpRegenerateRequest",
    "TotpSetupRequest",
    "TotpSetupResponse",
    "TotpStatusResponse",
    "TotpVerifyRequest",
    "UpdateMeRequest",
    "RegisterRequest",
    "UserOut",
]
