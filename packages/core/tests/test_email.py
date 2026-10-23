"""AL-5: one generic EmailSender.send(to, subject, text) for every service."""

from __future__ import annotations

import logging
from email.message import EmailMessage
from typing import Any

import pytest

from strong_core import email as core_email
from strong_core.config import Settings


class FakeSmtp:
    instances: list[FakeSmtp] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.timeout = host, port, timeout
        self.calls: list[str] = []
        self.sent: list[EmailMessage] = []
        FakeSmtp.instances.append(self)

    def __enter__(self) -> FakeSmtp:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.calls.append("quit")

    def starttls(self) -> None:
        self.calls.append("starttls")

    def login(self, user: str, password: str) -> None:
        self.calls.append(f"login {user}")

    def send_message(self, msg: EmailMessage) -> None:
        self.sent.append(msg)


@pytest.fixture
def smtp(monkeypatch: pytest.MonkeyPatch) -> type[FakeSmtp]:
    FakeSmtp.instances = []
    monkeypatch.setattr(core_email.smtplib, "SMTP", FakeSmtp)
    return FakeSmtp


def test_factory_picks_console_without_smtp_host() -> None:
    assert isinstance(
        core_email.make_email_sender(Settings(_env_file=None)), core_email.ConsoleEmailSender
    )
    sender = core_email.make_email_sender(Settings(_env_file=None, smtp_host="smtp.example.com"))
    assert isinstance(sender, core_email.SmtpEmailSender)


async def test_smtp_sender_uses_starttls_and_login(smtp: type[FakeSmtp]) -> None:
    settings = Settings(
        _env_file=None,
        smtp_host="smtp.example.com",
        smtp_port=2525,
        smtp_username="user",
        smtp_password="pw",
        smtp_from="Strong Hire <ops@example.com>",
    )
    await core_email.make_email_sender(settings).send("to@example.com", "Hello", "Body text")
    (conn,) = smtp.instances
    assert (conn.host, conn.port) == ("smtp.example.com", 2525)
    assert conn.calls[:2] == ["starttls", "login user"]
    (msg,) = conn.sent
    assert msg["To"] == "to@example.com" and msg["Subject"] == "Hello"
    assert msg["From"] == "Strong Hire <ops@example.com>"
    assert msg.get_content().strip() == "Body text"


async def test_smtp_sender_skips_login_without_credentials(smtp: type[FakeSmtp]) -> None:
    sender = core_email.SmtpEmailSender("smtp.example.com", from_addr="a@example.com")
    await sender.send("to@example.com", "s", "t")
    assert "login" not in " ".join(smtp.instances[0].calls)


async def test_console_sender_logs(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="strong_core.email"):
        await core_email.ConsoleEmailSender().send("to@example.com", "Subject", "Text")
    assert "to@example.com" in caplog.text and "Subject" in caplog.text


def test_admin_settings_are_optional() -> None:
    """D-10 ALERT_EMAIL and D-12 INFRA_MONTHLY_USD default to empty."""
    s = Settings(_env_file=None)
    assert s.alert_email == "" and s.infra_monthly_usd is None
