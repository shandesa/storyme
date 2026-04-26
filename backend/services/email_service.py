"""
services/email_service.py
==========================
Email delivery for StoryMe — PDF storybook attachments.

Configuration (environment variables):
    SMTP_HOST       SMTP server hostname        (default: smtp.gmail.com)
    SMTP_PORT       SMTP server port            (default: 587)
    SMTP_USER       SMTP username / from address
    SMTP_PASSWORD   SMTP password / app password
    SMTP_FROM       Display sender (default: SMTP_USER)
    SMTP_TLS        "true" | "false"            (default: true — STARTTLS)

If SMTP_USER or SMTP_PASSWORD is not set the service logs a warning and
returns False (no-op). All other StoryMe functionality is unaffected.

Usage:
    from services.email_service import email_service
    ok = await email_service.send_pdf_email(
        to="parent@example.com",
        child_name="Aanya",
        pdf_path="/path/to/aanya_storybook.pdf",
    )
"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
from email.message import EmailMessage
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class EmailService:
    """Send PDF storybooks via SMTP. No-op when SMTP is not configured."""

    # ── Config ────────────────────────────────────────────────────────────────

    @staticmethod
    def _cfg() -> dict:
        return {
            "host":     os.environ.get("SMTP_HOST",     "smtp.gmail.com"),
            "port":     int(os.environ.get("SMTP_PORT", "587")),
            "user":     os.environ.get("SMTP_USER",     ""),
            "password": os.environ.get("SMTP_PASSWORD", ""),
            "from":     os.environ.get("SMTP_FROM",     "") or os.environ.get("SMTP_USER", ""),
            "tls":      os.environ.get("SMTP_TLS",      "true").lower() != "false",
        }

    def is_configured(self) -> bool:
        cfg = self._cfg()
        return bool(cfg["user"] and cfg["password"])

    # ── Public ────────────────────────────────────────────────────────────────

    async def send_pdf_email(
        self,
        to: str,
        child_name: str,
        pdf_path: str,
        order_id: Optional[str] = None,
    ) -> bool:
        """
        Send a PDF storybook to the given email address.

        Args:
            to:         Recipient email address
            child_name: Child's name (used in subject + body)
            pdf_path:   Absolute or relative path to the PDF file on disk
            order_id:   Optional order reference for the email footer

        Returns:
            True if email was sent, False if not configured or on error.
        """
        if not self.is_configured():
            logger.warning(
                "EmailService: SMTP not configured (SMTP_USER/SMTP_PASSWORD missing). "
                "Would have sent PDF to %s for %r. "
                "Set SMTP_USER and SMTP_PASSWORD env vars to enable email delivery.",
                to, child_name,
            )
            return False

        if not Path(pdf_path).exists():
            logger.error("EmailService: PDF not found at %s — cannot send to %s", pdf_path, to)
            return False

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._send_sync, to, child_name, pdf_path, order_id
        )

    # ── Internal ──────────────────────────────────────────────────────────────

    def _send_sync(
        self,
        to: str,
        child_name: str,
        pdf_path: str,
        order_id: Optional[str],
    ) -> bool:
        """Blocking SMTP send — runs in thread executor."""
        import smtplib

        cfg = self._cfg()
        pdf_file = Path(pdf_path)

        msg = EmailMessage()
        msg["Subject"] = f"Your StoryMe Storybook — {child_name}'s Adventure!"
        msg["From"]    = f"StoryMe <{cfg['from']}>" if cfg["from"] else "StoryMe"
        msg["To"]      = to

        # Plain text body
        body = (
            f"Hi there,\n\n"
            f"Your personalised storybook for {child_name} is attached as a PDF.\n\n"
            f"Open it on any device — you can also print it at home or at a print shop.\n\n"
        )
        if order_id:
            body += f"Order reference: {order_id[:12].upper()}\n\n"
        body += (
            "We hope {name} loves their story!\n\n"
            "— The StoryMe Team\n"
        ).format(name=child_name)
        msg.set_content(body)

        # Attach PDF
        ctype, encoding = mimetypes.guess_type(str(pdf_file))
        if ctype is None or encoding is not None:
            ctype = "application/octet-stream"
        maintype, subtype = ctype.split("/", 1)
        with open(pdf_path, "rb") as f:
            pdf_data = f.read()
        msg.add_attachment(
            pdf_data,
            maintype=maintype,
            subtype=subtype,
            filename=pdf_file.name,
        )

        try:
            if cfg["tls"]:
                with smtplib.SMTP(cfg["host"], cfg["port"]) as s:
                    s.ehlo()
                    s.starttls()
                    s.login(cfg["user"], cfg["password"])
                    s.send_message(msg)
            else:
                with smtplib.SMTP_SSL(cfg["host"], cfg["port"]) as s:
                    s.login(cfg["user"], cfg["password"])
                    s.send_message(msg)

            logger.info(
                "EmailService: PDF sent to %s for %r (order=%s pdf=%s bytes)",
                to, child_name, (order_id or "—")[:12], len(pdf_data),
            )
            return True

        except Exception as e:
            logger.error(
                "EmailService: send failed to %s for %r: %s",
                to, child_name, e, exc_info=True,
            )
            return False


# Singleton
email_service = EmailService()
