"""Sign-in emails: magic link, email confirmation, password reset. Local development logs the
link instead of sending it."""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from strong_api.auth.settings import AuthSettings

log = logging.getLogger(__name__)


class EmailSender(Protocol):
    async def send_magic_link(self, to: str, link: str) -> None: ...
    async def send_email_confirmation(self, to: str, link: str) -> None: ...
    async def send_password_reset(self, to: str, link: str) -> None: ...
    async def send_account_exists(self, to: str, signin_url: str) -> None: ...


def _magic_link(minutes: int, link: str) -> tuple[str, str]:
    return "Your Strong Hire sign-in link", (
        f"Use this link to sign in to Strong Hire. It works once, for {minutes} minutes.\n\n"
        f"{link}\n\nIf you did not ask for this email, you can ignore it."
    )


def _confirmation(hours: int, link: str) -> tuple[str, str]:
    return "Confirm your email for Strong Hire", (
        "Thanks for signing up for Strong Hire. Open this link to confirm your email and sign "
        f"in. It works once, for {hours} hours.\n\n{link}\n\n"
        "If you did not sign up, you can ignore this email. No account is used without it."
    )


def _reset(minutes: int, link: str) -> tuple[str, str]:
    return "Reset your Strong Hire password", (
        f"Use this link to choose a new password. It works once, for {minutes} minutes.\n\n"
        f"{link}\n\nIf you did not ask for this email, you can ignore it. "
        "Your password stays the same."
    )


def _exists(signin_url: str) -> tuple[str, str]:
    return "You already have a Strong Hire account", (
        "Someone tried to create a Strong Hire account with this email, and you already have "
        f"one. Sign in here:\n\n{signin_url}\n\n"
        'If you forgot your password, choose "Forgot password?" on that page. If this was not '
        "you, you can ignore this email."
    )


class ConsoleEmailSender:
    async def send_magic_link(self, to: str, link: str) -> None:
        log.warning("Magic link for %s: %s", to, link)

    async def send_email_confirmation(self, to: str, link: str) -> None:
        log.warning("Email confirmation link for %s: %s", to, link)

    async def send_password_reset(self, to: str, link: str) -> None:
        log.warning("Password reset link for %s: %s", to, link)

    async def send_account_exists(self, to: str, signin_url: str) -> None:
        log.warning("Account exists email for %s: %s", to, signin_url)


class SmtpEmailSender:
    def __init__(self, settings: AuthSettings) -> None:
        self._s = settings

    async def send_magic_link(self, to: str, link: str) -> None:
        await self._deliver(to, *_magic_link(self._s.magic_link_max_age_s // 60, link))

    async def send_email_confirmation(self, to: str, link: str) -> None:
        await self._deliver(to, *_confirmation(self._s.confirm_link_max_age_s // 3600, link))

    async def send_password_reset(self, to: str, link: str) -> None:
        await self._deliver(to, *_reset(self._s.reset_link_max_age_s // 60, link))

    async def send_account_exists(self, to: str, signin_url: str) -> None:
        await self._deliver(to, *_exists(signin_url))

    async def _deliver(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = self._s.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        await asyncio.to_thread(self._send, msg)

    def _send(self, msg: EmailMessage) -> None:
        assert self._s.smtp_host
        with smtplib.SMTP(self._s.smtp_host, self._s.smtp_port, timeout=10) as smtp:
            smtp.starttls()
            if self._s.smtp_username and self._s.smtp_password:
                smtp.login(self._s.smtp_username, self._s.smtp_password)
            smtp.send_message(msg)


def make_email_sender(settings: AuthSettings) -> EmailSender:
    return SmtpEmailSender(settings) if settings.smtp_host else ConsoleEmailSender()
