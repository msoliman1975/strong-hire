"""Emails Strova sends (SV-9): plan reminders today, and other product emails as they are added.

They come from "Strova from Strong Hire" (the address stays SMTP_FROM's) and show the 64 px
coaching avatar beside the Strong Hire logo, both as inline images. Account emails (sign-in,
confirmation, password reset, billing) keep the Strong Hire sender and no avatar; they do not use
this module.
"""

from __future__ import annotations

from functools import cache
from html import escape
from pathlib import Path

from strong_core.email import Email, InlineImage

FROM_NAME = "Strova from Strong Hire"
AVATAR_CID = "strova"
LOGO_CID = "strong-hire"
ASSETS = Path(__file__).parent / "assets"


@cache
def _image(name: str) -> bytes:
    return (ASSETS / name).read_bytes()


def strova_email(
    to: str,
    subject: str,
    lines: list[str],
    *,
    action_label: str | None = None,
    action_url: str | None = None,
    footer: str | None = None,
) -> Email:
    """A product email from Strova: greeting and lines, one action link, a footer line."""
    text_parts = [*lines]
    if action_label and action_url:
        text_parts.append(f"{action_label}: {action_url}")
    text_parts.append("Strova")
    if footer:
        text_parts.append(footer)
    paragraphs = "".join(f'<p style="margin:0 0 12px">{escape(line)}</p>' for line in lines)
    button = (
        f'<p style="margin:16px 0"><a href="{escape(action_url)}" style="background:#5332e6;'
        f"color:#ffffff;padding:10px 16px;border-radius:999px;text-decoration:none;"
        f'font-weight:600">{escape(action_label)}</a></p>'
        if action_label and action_url
        else ""
    )
    small = (
        f'<p style="margin:24px 0 0;color:#5e5b6b;font-size:13px">{escape(footer)}</p>'
        if footer
        else ""
    )
    html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;color:#17161f;max-width:560px">'
        '<table role="presentation" style="margin:0 0 16px"><tr>'
        f'<td><img src="cid:{LOGO_CID}" alt="Strong Hire" width="32" height="32"></td>'
        f'<td style="padding:0 12px 0 8px;font-weight:700">Strong Hire</td>'
        f'<td><img src="cid:{AVATAR_CID}" alt="Strova" width="64" height="64"></td>'
        "</tr></table>"
        f"{paragraphs}{button}"
        '<p style="margin:0">Strova</p>'
        f"{small}</div>"
    )
    return Email(
        to=to,
        subject=subject,
        text="\n\n".join(text_parts),
        html=html,
        from_name=FROM_NAME,
        images=(
            InlineImage(cid=LOGO_CID, data=_image("strong-hire-logo-64.png")),
            InlineImage(cid=AVATAR_CID, data=_image("strova-coaching-64.png")),
        ),
    )
