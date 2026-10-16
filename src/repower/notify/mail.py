"""Send an HTML + plain-text email over SMTP (stdlib only).

Configured from ``repower.config`` (``SMTP_*`` / ``MAIL_*``, read at call time so
tests and the CLI can override them). Unconfigured is not an error — callers get
``False`` and decide; a configured send that fails raises :class:`EmailError`.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from repower import config

logger = logging.getLogger(__name__)

TIMEOUT_S = 30.0
ATTEMPTS = 3
BACKOFF_S = 5.0


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


def _describe(e: Exception, stage: str) -> str:
    """One line naming the stage, the exception and its detail — with credentials removed."""
    detail = getattr(e, "smtp_error", None) or (e.args[0] if e.args else "")
    if isinstance(detail, bytes):
        detail = detail.decode("utf-8", "replace")
    detail = " ".join(str(detail).split())
    for secret in (config.SMTP_PASSWORD, config.SMTP_USER):
        if secret:
            detail = detail.replace(secret, "***")
    code = getattr(e, "smtp_code", None)
    return f"email send failed at {stage}: {type(e).__name__}" + (f" ({code})" if code else "") + (
        f" — {detail}" if detail else "")


def send_email(subject: str, text: str, html: str) -> bool:
    """Send to ``MAIL_TO``. Returns False (no-op) when SMTP/recipients are unset.

    A dropped connection or a network error is retried (``ATTEMPTS`` tries, short
    backoff): Gmail occasionally closes a fresh connection from a CI runner. An SMTP
    *reply* — bad credentials, a rejected recipient — is deterministic and fails at once.
    """
    if not is_configured():
        return False
    to = recipients()
    sender = config.MAIL_FROM or config.SMTP_USER
    msg = build_message(subject, text, html, sender=sender, to=to)
    for attempt in range(1, ATTEMPTS + 1):
        stage = "connect"
        try:
            with smtplib.SMTP_SSL(
                config.SMTP_HOST, config.SMTP_PORT, timeout=TIMEOUT_S, context=ssl.create_default_context(),
            ) as smtp:
                stage = "login"
                smtp.login(config.SMTP_USER, config.SMTP_PASSWORD)
                stage = "send"
                smtp.send_message(msg)
            break
        except smtplib.SMTPResponseException as e:
            # A reply from the server (bad credentials, rejected recipient) is deterministic —
            # no retry. Matched first: SMTPException subclasses OSError.
            raise EmailError(_describe(e, stage)) from e
        except (smtplib.SMTPException, OSError) as e:
            # No reply: SMTPServerDisconnected, DNS, timeout, reset, TLS. Can be transient.
            logger.warning("attempt %d/%d: %s", attempt, ATTEMPTS, _describe(e, stage))
            if attempt == ATTEMPTS:
                raise EmailError(_describe(e, stage)) from e
            time.sleep(BACKOFF_S * attempt)
    logger.info("email sent to %d recipient(s)", len(to))
    return True
