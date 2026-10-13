"""Email sender abstraction.

v1 ships `LoggingEmailSender` (logs instead of sending) so the password-reset
flow runs end-to-end with no email infrastructure. Enabling real email later =
implement `EmailSender` for your provider (SMTP/SendGrid/SES) and wire it up;
no schema or endpoint changes required.
"""

from __future__ import annotations

from typing import Protocol


class EmailSender(Protocol):
    """Protocol for email delivery. Swap LoggingEmailSender for a real impl later."""

    async def send(self, to: str, subject: str, body: str) -> None: ...


class LoggingEmailSender:
    """Default sender: logs instead of sending. Lets the reset flow run with no infra."""

    async def send(self, to: str, subject: str, body: str) -> None:
        # Intentionally print to stdout — visible in dev logs / test captures.
        print(f"[email] to={to!r} subject={subject!r}\nbody:\n{body}\n[end email]")


__all__ = ["EmailSender", "LoggingEmailSender"]
