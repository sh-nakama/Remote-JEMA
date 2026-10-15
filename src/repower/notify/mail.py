"""Send an HTML + plain-text email over SMTP (stdlib only).

Configured from ``repower.config`` (``SMTP_*`` / ``MAIL_*``, read at call time so
tests and the CLI can override them). Unconfigured is not an error — callers get
``False`` and decide; a configured send that fails raises :class:`EmailError`.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from repower import config

logger = logging.getLogger(__name__)

TIMEOUT_S = 30.0


class EmailError(RuntimeError):
    """A configured email could not be sent."""


def recipients(raw: str | None = None) -> list[str]:
    """The comma/semicolon-separated ``MAIL_TO`` as a clean list."""
    raw = config.MAIL_TO if raw is None else raw
    return [a.strip() for a in raw.replace(";", ",").split(",") if a.strip()]


def is_configured() -> bool:
    return bool(config.SMTP_USER and config.SMTP_PASSWORD and recipients())


def build_message(subject: str, text: str, html: str, *, sender: str, to: list[str]) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr(("JEMA", sender))
    msg["To"] = ", ".join(to)
    msg["Message-ID"] = make_msgid(domain=sender.rpartition("@")[2] or None)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    return msg


def send_email(subject: str, text: str, html: str) -> bool:
    """Send to ``MAIL_TO``. Returns False (no-op) when SMTP/recipients are unset."""
    if not is_configured():
        return False
    to = recipients()
    sender = config.MAIL_FROM or config.SMTP_USER
    msg = build_message(subject, text, html, sender=sender, to=to)
    try:
        with smtplib.SMTP_SSL(
            config.SMTP_HOST, config.SMTP_PORT, timeout=TIMEOUT_S, context=ssl.create_default_context(),
        ) as smtp:
            smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        # The class name and SMTP reply code are enough to diagnose; never echo credentials.
        code = getattr(e, "smtp_code", None)
        raise EmailError(f"email send failed: {type(e).__name__}" + (f" ({code})" if code else "")) from e
    logger.info("email sent to %d recipient(s)", len(to))
    return True
