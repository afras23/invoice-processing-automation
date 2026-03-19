"""
Slack integration.

Sends notifications via an incoming webhook URL.
"""

import logging

import httpx

from app.config import settings
from app.core.exceptions import IntegrationError

logger = logging.getLogger(__name__)


def send_slack_notification(text: str) -> None:
    """
    Post a message to Slack via the configured webhook.

    Silently skips if SLACK_WEBHOOK_URL is not configured.

    Args:
        text: Message body to send.

    Raises:
        IntegrationError: If the HTTP call to Slack fails.
    """
    if not settings.slack_webhook_url:
        logger.debug("Slack notification skipped: SLACK_WEBHOOK_URL not configured")
        return

    try:
        response = httpx.post(
            settings.slack_webhook_url,
            json={"text": text},
            timeout=10.0,
        )
        response.raise_for_status()
        logger.info("Slack notification sent")
    except httpx.HTTPError as e:
        raise IntegrationError(f"Failed to send Slack notification: {e}") from e
