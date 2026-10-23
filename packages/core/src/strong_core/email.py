"""Plain-text email for every service (AL-5). Without SMTP_HOST, emails are logged instead.

    sender = make_email_sender()
    await sender.send("ops@example.com", "Alert: API down", "The /health probe ...")

The API's sign-in emails (magic link, confirmation, reset) are built on this sender.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from strong_core.config import Settings, get_settings

log = logging.getLogger(__name__)

SMTP_TIMEOUT_S = 10


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, text: str) -> None: ...


class ConsoleEmailSender:
    """Local development: writes the email to the log instead of sending it."""

    async def send(self, to: str, subject: str, text: str) -> None:
        log.warning("Email to %s: %s\n%s", to, subject, text)


class SmtpEmailSender:
    """Sends through an SMTP server with STARTTLS (port 587). Raises when sending fails."""

    def __init__(
        self,
        host: str,
        *,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        from_addr: str,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.from_addr = from_addr

    async def send(self, to: str, subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.from_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        await asyncio.to_thread(self._send, msg)

    def _send(self, msg: EmailMessage) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=SMTP_TIMEOUT_S) as smtp:
            smtp.starttls()
            if self.username and self.password:
                smtp.login(self.username, self.password)
            smtp.send_message(msg)


def make_email_sender(settings: Settings | None = None) -> EmailSender:
    """SMTP when SMTP_HOST is set, else the console sender."""
    s = settings or get_settings()
    if not s.smtp_host:
        return ConsoleEmailSender()
    return SmtpEmailSender(
        s.smtp_host,
        port=s.smtp_port,
        username=s.smtp_username,
        password=s.smtp_password,
        from_addr=s.smtp_from,
    )
