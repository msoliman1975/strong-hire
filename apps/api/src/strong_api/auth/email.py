"""Sending the magic link email. Local development logs the link instead of sending it."""

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


class ConsoleEmailSender:
    async def send_magic_link(self, to: str, link: str) -> None:
        log.warning("Magic link for %s: %s", to, link)


class SmtpEmailSender:
    def __init__(self, settings: AuthSettings) -> None:
        self._s = settings

    async def send_magic_link(self, to: str, link: str) -> None:
        msg = EmailMessage()
        msg["From"] = self._s.smtp_from
        msg["To"] = to
        msg["Subject"] = "Your Strong Hire sign-in link"
        minutes = self._s.magic_link_max_age_s // 60
        msg.set_content(
            f"Use this link to sign in to Strong Hire. It works once, for {minutes} minutes.\n\n"
            f"{link}\n\nIf you did not ask for this email, you can ignore it."
        )
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
