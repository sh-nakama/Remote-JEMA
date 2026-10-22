"""Send an HTML + plain-text email over SMTP (stdlib only).

Configured from ``repower.config`` (``SMTP_*`` / ``MAIL_*``, read at call time so
tests and the CLI can override them). Unconfigured is not an error — callers get
``False`` and decide; a configured send that fails raises :class:`EmailError`.
"""

from __future__ import annotations

import logging
import re
import smtplib
import ssl
import time
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

from repower import config

logger = logging.getLogger(__name__)

TIMEOUT_S = 30.0
ATTEMPTS = 3
IMPLICIT_TLS_PORT = 465
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


# What an SMTP rejection means for a Gmail sender, keyed by reply code.
_HINTS = {
    534: "Gmail wants an App Password here, not the account password",
    535: ("Gmail rejected the username/App Password: SMTP_USER must be the full address the App "
          "Password was created under, and SMTP_PASSWORD a current App Password (changing the Google "
          "password or turning off 2-Step Verification revokes them)"),
    454: "Gmail is temporarily refusing this sign-in; sign in to the account in a browser and retry",
}
# Google shows an App Password as four groups of four letters; the spaces are display only.
_APP_PASSWORD_RE = re.compile(r"[a-z]{4}(?: [a-z]{4}){3}")


def _password(raw: str) -> str:
    pw = raw.strip()  # a pasted secret often ends in a newline
    return pw.replace(" ", "") if _APP_PASSWORD_RE.fullmatch(pw) else pw


def _describe(e: Exception, stage: str) -> str:
    """One line naming the stage, the exception and its detail — with credentials removed."""
    detail = getattr(e, "smtp_error", None) or (e.args[0] if e.args else "")
    if isinstance(detail, bytes):
        detail = detail.decode("utf-8", "replace")
    detail = " ".join(str(detail).split())
    for secret in (config.SMTP_PASSWORD, _password(config.SMTP_PASSWORD), config.SMTP_USER.strip()):
        if secret:
            detail = detail.replace(secret, "***")
    code = getattr(e, "smtp_code", None)
    hint = _HINTS.get(code) if isinstance(code, int) else None
    return f"email send failed at {stage}: {type(e).__name__}" + (f" ({code})" if code else "") + (
        f" — {detail}" if detail else "") + (f". {hint}" if hint else "")


def _authenticate(smtp: smtplib.SMTP, user: str, password: str) -> None:
    """Log in with a single AUTH mechanism, so a rejection surfaces as the server's reply.

    ``smtplib.SMTP.login`` tries every advertised mechanism in turn and swallows the
    rejection of all but the last. Gmail rejects AUTH PLAIN (say ``535 5.7.8
    BadCredentials``) and then hangs up, so the AUTH LOGIN fallback dies with
    ``SMTPServerDisconnected`` and the reply saying what is wrong is lost — which is all
    the first weekly-email runs ever reported.
    """
    if not smtp.has_extn("auth"):
        raise smtplib.SMTPNotSupportedError(
            "the server offers no AUTH (is something on this network intercepting SMTP?)")
    offered = smtp.esmtp_features.get("auth", "").upper().split()
    method = next((m for m in ("PLAIN", "LOGIN") if m in offered), None)
    if method is None:
        raise smtplib.SMTPNotSupportedError(f"no usable AUTH mechanism (server offers {' '.join(offered)})")
    smtp.user, smtp.password = user, password
    smtp.auth(method, getattr(smtp, f"auth_{method.lower()}"))  # raises SMTPAuthenticationError


def _connect() -> smtplib.SMTP:
    """Implicit TLS on 465 (Gmail's default), STARTTLS on any other port (e.g. 587)."""
    if config.SMTP_PORT == IMPLICIT_TLS_PORT:
        return smtplib.SMTP_SSL(
            config.SMTP_HOST, config.SMTP_PORT, timeout=TIMEOUT_S, context=ssl.create_default_context(),
        )
    return smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=TIMEOUT_S)


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
    user, password = config.SMTP_USER.strip(), _password(config.SMTP_PASSWORD)
    for attempt in range(1, ATTEMPTS + 1):
        stage = "connect"
        try:
            with _connect() as smtp:
                if config.SMTP_PORT != IMPLICIT_TLS_PORT:
                    stage = "starttls"
                    smtp.ehlo()
                    smtp.starttls(context=ssl.create_default_context())
                stage = "ehlo"
                smtp.ehlo()
                stage = "login"
                _authenticate(smtp, user, password)
                stage = "send"
                smtp.send_message(msg)
            break
        except (smtplib.SMTPResponseException, smtplib.SMTPNotSupportedError) as e:
            # A reply from the server (bad credentials, rejected recipient) or a missing
            # capability is deterministic — no retry. Matched first: SMTPException subclasses OSError.
            raise EmailError(_describe(e, stage)) from e
        except (smtplib.SMTPException, OSError) as e:
            # No reply: SMTPServerDisconnected, DNS, timeout, reset, TLS. Can be transient.
            logger.warning("attempt %d/%d: %s", attempt, ATTEMPTS, _describe(e, stage))
            if attempt == ATTEMPTS:
                raise EmailError(_describe(e, stage)) from e
            time.sleep(BACKOFF_S * attempt)
    logger.info("email sent to %d recipient(s)", len(to))
    return True
