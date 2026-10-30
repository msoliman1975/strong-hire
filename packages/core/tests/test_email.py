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


async def test_sv9_rich_email_has_the_sender_name_html_and_the_inline_avatar(
    smtp: type[FakeSmtp],
) -> None:
    """SV-9: Strova's emails carry "Strova from Strong Hire" with SMTP_FROM's address, a text
    part, an HTML part and the avatar as an inline image the HTML shows by cid."""
    sender = core_email.SmtpEmailSender(
        "smtp.example.com", from_addr="Strong Hire <no-reply@stronghire.example>"
    )
    email = core_email.Email(
        to="ana@example.com",
        subject="Your debrief is ready",
        text="Hi Ana",
        html='<p><img src="cid:strova" alt="Strova" width="64"> Hi Ana</p>',
        from_name="Strova from Strong Hire",
        images=(core_email.InlineImage(cid="strova", data=b"\\x89PNG fake"),),
    )
    await core_email.send_email(sender, email)
    (msg,) = smtp.instances[0].sent
    assert msg["From"] == "Strova from Strong Hire <no-reply@stronghire.example>"
    text = msg.get_body(preferencelist=("plain",))
    html = msg.get_body(preferencelist=("html",))
    assert text is not None and text.get_content().strip() == "Hi Ana"
    assert html is not None and 'src="cid:strova"' in html.get_content()
    images = [p for p in msg.walk() if p.get_content_type() == "image/png"]
    assert len(images) == 1 and images[0]["Content-ID"] == "<strova>"


async def test_sv9_account_emails_keep_the_strong_hire_sender(smtp: type[FakeSmtp]) -> None:
    """SV-9: without a display name the sender stays SMTP_FROM, and a plain sender (no
    send_message) gets the text part."""
    sender = core_email.SmtpEmailSender(
        "smtp.example.com", from_addr="Strong Hire <no-reply@stronghire.example>"
    )
    await sender.send("ana@example.com", "Sign in", "Your link")
    assert smtp.instances[0].sent[0]["From"] == "Strong Hire <no-reply@stronghire.example>"

    class Plain:
        def __init__(self) -> None:
            self.sent: list[tuple[str, str, str]] = []

        async def send(self, to: str, subject: str, text: str) -> None:
            self.sent.append((to, subject, text))

    plain = Plain()
    await core_email.send_email(
        plain, core_email.Email(to="a@b.c", subject="S", text="T", html="<p>T</p>", from_name="X")
    )
    assert plain.sent == [("a@b.c", "S", "T")]
