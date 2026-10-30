"""Email for every service (AL-5). Without SMTP_HOST, emails are logged instead.

    sender = make_email_sender()
    await sender.send("ops@example.com", "Alert: API down", "The /health probe ...")

The API's sign-in emails (magic link, confirmation, reset) are built on this sender.

SV-9: product emails from Strova (debrief ready, plan reminders) are an `Email` with an HTML
part, inline images and a sender display name ("Strova from Strong Hire"), sent with
`send_email`. A sender without `send_message` (test fakes, older senders) gets the plain text.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from typing import Protocol, runtime_checkable

from strong_core.config import Settings, get_settings

log = logging.getLogger(__name__)

SMTP_TIMEOUT_S = 10


class EmailSender(Protocol):
    async def send(self, to: str, subject: str, text: str) -> None: ...


@dataclass(frozen=True)
class InlineImage:
    """An image the HTML part shows with <img src="cid:{cid}">."""

    cid: str
    data: bytes
    subtype: str = "png"


@dataclass(frozen=True)
class Email:
    """SV-9: a product email with a plain-text part, an optional HTML part with inline images,
    and an optional sender display name (the address stays SMTP_FROM's)."""

    to: str
    subject: str
    text: str
    html: str | None = None
    from_name: str | None = None
    images: tuple[InlineImage, ...] = field(default_factory=tuple)


@runtime_checkable
class RichEmailSender(Protocol):
    async def send_message(self, email: Email) -> None: ...


async def send_email(sender: EmailSender, email: Email) -> None:
    """Send `email` with its HTML and sender name when the sender can, else as plain text."""
    if isinstance(sender, RichEmailSender):
        await sender.send_message(email)
    else:
        await sender.send(email.to, email.subject, email.text)


def build_message(email: Email, from_addr: str) -> EmailMessage:
    """The MIME message: text, then HTML as the alternative, with images related to the HTML."""
    msg = EmailMessage()
    name, addr = parseaddr(from_addr)
    msg["From"] = formataddr((email.from_name or name, addr)) if (email.from_name or name) else addr
    msg["To"] = email.to
    msg["Subject"] = email.subject
    msg.set_content(email.text)
    if email.html is not None:
        msg.add_alternative(email.html, subtype="html")
        html_part = msg.get_payload()[-1]
        assert isinstance(html_part, EmailMessage)
        for image in email.images:
            html_part.add_related(
                image.data, maintype="image", subtype=image.subtype, cid=f"<{image.cid}>"
            )
    return msg


class ConsoleEmailSender:
    """Local development: writes the email to the log instead of sending it."""

    async def send(self, to: str, subject: str, text: str) -> None:
        log.warning("Email to %s: %s\n%s", to, subject, text)

    async def send_message(self, email: Email) -> None:
        sender = f" from {email.from_name}" if email.from_name else ""
        log.warning("Email to %s%s: %s\n%s", email.to, sender, email.subject, email.text)


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

    async def send_message(self, email: Email) -> None:
        await asyncio.to_thread(self._send, build_message(email, self.from_addr))

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
