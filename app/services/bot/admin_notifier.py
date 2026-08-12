"""Admin Notification Service — Sends Telegram Bot alerts to admin on user events."""

import logging
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)


async def notify_admin(text: str) -> bool:
    """Send Markdown formatted notification message to ADMIN_TELEGRAM_CHAT_ID via Telegram Bot API."""
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.ADMIN_TELEGRAM_CHAT_ID

    if not token or not chat_id:
        logger.debug("ADMIN_TELEGRAM_CHAT_ID or TELEGRAM_BOT_TOKEN not configured. Skipping admin notification.")
        return False

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, json=payload)
            if res.status_code == 200:
                logger.info(f"Successfully sent admin notification to chat [{chat_id}]")
                return True
            else:
                logger.warning(f"Failed to send admin notification. Status: {res.status_code}, body: {res.text}")
                return False
    except Exception as e:
        logger.error(f"Error sending admin notification: {e}")
        return False
