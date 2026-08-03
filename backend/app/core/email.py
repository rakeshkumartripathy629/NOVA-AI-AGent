"""
Email delivery service.

In production uses SMTP (or Mailgun/SendGrid if configured). During
development it logs emails and can dump them to disk for local testing.
"""
from __future__ import annotations

import logging
import re
import smtplib
from datetime import datetime
from email.message import EmailMessage
from email.mime.text import MIMEText
from pathlib import Path
from typing import List, Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmailServiceError(Exception):
    """Raised when an email cannot be sent."""


class EmailService:
    """Sends transactional emails."""

    def __init__(self) -> None:
        self.from_email = settings.EMAIL_FROM
        self.from_name = settings.EMAIL_FROM_NAME

    async def send_email(
        self,
        to: str,
        subject: str,
        body_html: Optional[str] = None,
        body_text: Optional[str] = None,
        cc: Optional[List[str]] = None,
    ) -> bool:
        """Send an email. Returns True on success."""
        try:
            smtp_configured = bool(settings.SMTP_HOST) and (
                bool(settings.SMTP_USER) or bool(settings.SMTP_PASSWORD)
            )
            if settings.ENVIRONMENT != "production" and not smtp_configured:
                # Dev fallback: log the message and dump it to disk
                logger.info(
                    "Email [%s] -> %s: %s",
                    subject,
                    to,
                    body_text or "html",
                )
                self._dump_to_disk(to, subject, body_text or body_html or "")
                return True

            message = EmailMessage()
            message["Subject"] = subject
            message["From"] = f"{self.from_name} <{self.from_email}>"
            message["To"] = to
            if cc:
                message["Cc"] = ", ".join(cc)

            if body_text:
                message.set_content(body_text)
            if body_html:
                if body_text:
                    message.add_alternative(body_html, subtype="html")
                else:
                    message.set_content(body_html, subtype="html")

            if settings.SMTP_SSL:
                server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
            else:
                server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
                if settings.SMTP_TLS:
                    server.starttls()
            try:
                if settings.SMTP_USER:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
                server.send_message(message)
            finally:
                server.quit()
            return True
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to send email to %s", to)
            raise EmailServiceError(str(exc)) from exc

    def _dump_to_disk(self, to: str, subject: str, body: str) -> None:
        """Write a dev email to disk so it can be inspected locally."""
        try:
            dump_dir = Path(settings.DEV_EMAIL_DIR)
            dump_dir.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r"[^A-Za-z0-9_.@-]", "_", to)
            filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{safe_name}.txt"
            (dump_dir / filename).write_text(
                f"To: {to}\nSubject: {subject}\n\n{body}",
                encoding="utf-8",
            )
            logger.info("Dev email dumped to %s", dump_dir / filename)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to dump dev email to disk")


email_service = EmailService()
