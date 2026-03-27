"""
Email invoice parser.

Extracts invoice text from raw email content (RFC 2822 / MIME format).
Handles plain-text and HTML parts; strips HTML tags for downstream
AI extraction.
"""

from __future__ import annotations

import email
import html
import logging
import re
from email.message import Message

logger = logging.getLogger(__name__)

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def parse_email(raw_email: str | bytes, filename: str = "") -> str:
    """
    Extract invoice text from a raw email message.

    Prefers the plain-text part; falls back to stripping HTML tags from
    the HTML part when no plain-text alternative is present.

    Args:
        raw_email: Raw RFC 2822 email as a string or bytes.
        filename: Optional filename for log context.

    Returns:
        Extracted text content, stripped of leading/trailing whitespace.
    """
    if isinstance(raw_email, bytes):
        raw_email = raw_email.decode("utf-8", errors="replace")

    parsed_message: Message = email.message_from_string(raw_email)

    plain_text = _extract_plain_text(parsed_message)
    if plain_text:
        logger.info("Email parsed (plain-text part)", extra={"source_file": filename})
        return plain_text.strip()

    html_text = _extract_html_text(parsed_message)
    if html_text:
        logger.info("Email parsed (HTML part, tags stripped)", extra={"source_file": filename})
        return html_text.strip()

    logger.warning("Email had no extractable text", extra={"source_file": filename})
    return ""


# ── private helpers ───────────────────────────────────────────────────────────


def _extract_plain_text(message: Message) -> str:
    """Walk MIME parts and collect plain-text payloads."""
    parts: list[str] = []
    for part in message.walk():
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                parts.append(payload.decode("utf-8", errors="replace"))
    return "\n".join(parts)


def _extract_html_text(message: Message) -> str:
    """Walk MIME parts, collect HTML payloads, and strip tags."""
    parts: list[str] = []
    for part in message.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload(decode=True)
            if isinstance(payload, bytes):
                html_content = payload.decode("utf-8", errors="replace")
                text = _HTML_TAG_RE.sub(" ", html_content)
                text = html.unescape(text)
                parts.append(text)
    return "\n".join(parts)
