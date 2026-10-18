"""Sign-in emails: magic link, email confirmation, password reset. Local development logs the
link instead of sending it. Delivery is strong_core.email's SMTP sender."""

from __future__ import annotations

import logging
from typing import Protocol

from strong_api.auth.settings import AuthSettings
from strong_core.email import SmtpEmailSender as CoreSmtpSender

log = logging.getLogger(__name__)


class EmailSender(Protocol):
    async def send_magic_link(self, to: str, link: str) -> None: ...
    async def send_email_confirmation(self, to: str, link: str) -> None: ...
    async def send_password_reset(self, to: str, link: str) -> None: ...


def _magic_link(minutes: int, link: str) -> tuple[str, str]:
    return "Your Strong Hire sign-in link", (
        f"Use this link to sign in to Strong Hire. It works once, for {minutes} minutes.\n\n"
        f"{link}\n\nIf you did not ask for this email, you can ignore it."
    )


def _confirmation(hours: int, link: str) -> tuple[str, str]:
    return "Confirm your email for Strong Hire", (
        "Thanks for signing up for Strong Hire. Open this link to confirm your email and sign "
        f"in. It works once, for {hours} hours.\n\n{link}\n\n"
        "If you did not sign up, you can ignore this email."
    )


def _reset(minutes: int, link: str) -> tuple[str, str]:
    return "Reset your Strong Hire password", (
        f"Use this link to choose a new password. It works once, for {minutes} minutes.\n\n"
        f"{link}\n\nIf you did not ask for this email, you can ignore it. "
        "Your password stays the same."
    )


class ConsoleEmailSender:
    async def send_magic_link(self, to: str, link: str) -> None:
        log.warning("Magic link for %s: %s", to, link)

    async def send_email_confirmation(self, to: str, link: str) -> None:
        log.warning("Email confirmation link for %s: %s", to, link)

    async def send_password_reset(self, to: str, link: str) -> None:
        log.warning("Password reset link for %s: %s", to, link)


class SmtpEmailSender:
    def __init__(self, settings: AuthSettings) -> None:
        if not settings.smtp_host:
            raise ValueError("SmtpEmailSender needs SMTP_HOST")
        self._s = settings
        self._smtp = CoreSmtpSender(
            settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            from_addr=settings.smtp_from,
        )

    async def send_magic_link(self, to: str, link: str) -> None:
        await self._deliver(to, *_magic_link(self._s.magic_link_max_age_s // 60, link))

    async def send_email_confirmation(self, to: str, link: str) -> None:
        await self._deliver(to, *_confirmation(self._s.confirm_link_max_age_s // 3600, link))

    async def send_password_reset(self, to: str, link: str) -> None:
        await self._deliver(to, *_reset(self._s.reset_link_max_age_s // 60, link))

    async def _deliver(self, to: str, subject: str, body: str) -> None:
        await self._smtp.send(to, subject, body)


def make_email_sender(settings: AuthSettings) -> EmailSender:
    return SmtpEmailSender(settings) if settings.smtp_host else ConsoleEmailSender()
