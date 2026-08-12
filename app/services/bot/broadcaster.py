"""User Notification Broadcaster Service — Broadcasts event announcements & discoveries to Telegram users."""

import asyncio
import logging
from typing import Optional, Dict, Any
import httpx
from sqlalchemy import select

from app.core.config import settings
from app.db.models import User
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def send_single_notification(
    token: str,
    chat_id: int,
    text: str,
    image_url: Optional[str] = None,
    button_text: str = "🚀 View in Mini App",
    web_app_url: str = ""
) -> bool:
    """Send photo or text Telegram notification message to a single user with inline WebApp button."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            reply_markup = {
                "inline_keyboard": [
                    [
                        {
                            "text": button_text,
                            "web_app": {"url": web_app_url}
                        }
                    ]
                ]
            }

            if image_url and image_url.startswith("http"):
                url = f"https://api.telegram.org/bot{token}/sendPhoto"
                payload = {
                    "chat_id": chat_id,
                    "photo": image_url,
                    "caption": text,
                    "parse_mode": "Markdown",
                    "reply_markup": reply_markup
                }
            else:
                url = f"https://api.telegram.org/bot{token}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                    "reply_markup": reply_markup
                }

            res = await client.post(url, json=payload)
            if res.status_code == 200:
                return True
            else:
                logger.debug(f"Broadcast to user [{chat_id}] returned status {res.status_code}: {res.text}")
                return False
    except Exception as e:
        logger.debug(f"Broadcast error for user [{chat_id}]: {e}")
        return False


async def broadcast_to_all_users(
    text: str,
    image_url: Optional[str] = None,
    button_text: str = "🚀 View in Mini App",
    mini_app_params: str = ""
) -> Dict[str, Any]:
    """Fetch all registered user Telegram IDs from database and broadcast notification message."""
    token = settings.TELEGRAM_BOT_TOKEN
    mini_app_base = settings.MINI_APP_URL
    if not token or not mini_app_base:
        logger.warning("TELEGRAM_BOT_TOKEN or MINI_APP_URL missing. Skipping broadcast.")
        return {"status": "error", "message": "Bot token or Mini App URL missing"}

    async with AsyncSessionLocal() as session:
        stmt = select(User.telegram_id)
        res = await session.execute(stmt)
        user_ids = list(res.scalars().all())

    if not user_ids:
        return {"status": "success", "total_targeted": 0, "successful_sent": 0}

    logger.info(f"Starting broadcast notification to {len(user_ids)} users...")
    success_count = 0

    # Rate limiting: semaphore limits concurrency to respect Telegram API rate limits
    semaphore = asyncio.Semaphore(15)

    async def worker(tg_id: int):
        nonlocal success_count
        async with semaphore:
            app_url = f"{mini_app_base}?{mini_app_params}" if mini_app_params else mini_app_base
            sent = await send_single_notification(
                token=token,
                chat_id=tg_id,
                text=text,
                image_url=image_url,
                button_text=button_text,
                web_app_url=app_url
            )
            if sent:
                success_count += 1
            await asyncio.sleep(0.05)

    tasks = [worker(uid) for uid in user_ids]
    await asyncio.gather(*tasks, return_exceptions=True)

    logger.info(f"Broadcast completed. Successfully delivered to {success_count}/{len(user_ids)} users.")
    return {
        "status": "success",
        "total_targeted": len(user_ids),
        "successful_sent": success_count
    }
