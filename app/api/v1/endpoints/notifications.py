"""Notification Broadcaster Endpoints — Protected API routes for triggering broadcasts."""

import html
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.config import settings
from app.core.security import require_api_key
from app.services.bot.broadcaster import broadcast_to_all_users, send_single_notification
from app.services.cache.redis_event_storage import RedisEventStorage

logger = logging.getLogger(__name__)
router = APIRouter()


def get_redis_storage() -> RedisEventStorage:
    return RedisEventStorage()


def build_post_url(item: dict) -> str:
    post_id = item.get("post_id", "unknown")
    platform = item.get("platform", "ig")
    post_url = item.get("metadata", {}).get("post_url") or item.get("post_url")
    if not post_url and platform in ("ig", "instagram"):
        post_url = f"https://www.instagram.com/p/{post_id}/"
    elif not post_url and platform in ("tg", "telegram"):
        ch = item.get("metadata", {}).get("handle_or_channel") or "addisevents"
        post_url = f"https://t.me/s/{ch}/{post_id}"
    return post_url or settings.MINI_APP_URL or "https://t.me"


@router.post(
    "/broadcast-scraped",
    summary="Broadcast Digest of Latest Extracted Events from Redis",
    description="Picks up to `limit` (default 3) latest extracted active events from Redis, formats them into a single digest with links, and sends to target_chat_id or broadcasts to all users.",
    dependencies=[Depends(require_api_key)]
)
async def broadcast_scraped_events(
    limit: int = Query(3, ge=1, le=5, description="Number of latest extracted events to include in digest (max 5)"),
    target_chat_id: Optional[int] = Query(None, description="Optional Telegram Chat ID to test sending to a single user/admin before broadcasting to all"),
    redis_storage: RedisEventStorage = Depends(get_redis_storage),
):
    """Fetches active scraped events from Redis, picks up to limit latest events, and sends digest to admin or broadcasts to all users."""
    try:
        raw_events = await redis_storage.get_all_active_events()
    except Exception as e:
        logger.error(f"Error fetching active Redis events for broadcast: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to read events from Redis cache."
        )

    if not raw_events:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active scraped events found in Redis cache."
        )

    # Sort events by stored_at ISO timestamp descending (newest first)
    raw_events.sort(key=lambda x: x.get("stored_at") or "", reverse=True)
    selected_items = raw_events[:limit]

    # Build multi-event digest message with HTML formatting
    lines = ["<b>✨ NEW EVENTS IN ADDIS ABABA 🎟️</b>\n"]

    for idx, item in enumerate(selected_items, start=1):
        evt_data = item.get("event", {})
        raw_title = evt_data.get("title") or "Upcoming Addis Social Event"
        title = html.escape(raw_title)

        venue_raw = evt_data.get("venue_name") or "Addis Ababa"
        venue = html.escape(venue_raw)

        fee_raw = evt_data.get("entrance_fee_etb")
        fee_str = f"{float(fee_raw):.0f} ETB" if fee_raw and float(fee_raw) > 0 else "FREE"

        raw_desc = evt_data.get("description") or evt_data.get("short_summary") or "Check out this upcoming event in Addis Ababa!"
        desc_clean = html.escape(raw_desc[:140] + ("..." if len(raw_desc) > 140 else ""))

        post_url = build_post_url(item)

        lines.append(
            f"<b>{idx}️⃣ {title}</b>\n"
            f"📍 <b>Venue</b>: {venue} | 💰 <b>Fee</b>: {fee_str}\n"
            f"📝 {desc_clean}\n"
            f"🔗 <a href=\"{post_url}\">View Source Post</a>\n"
        )

    lines.append("<i>Tap below to explore live events in PAZA Mini App!</i>")
    msg_text = "\n".join(lines)

    first_image = selected_items[0].get("event", {}).get("image_url") if selected_items else None

    # If target_chat_id is provided, send test notification to that specific admin/chat ID only
    if target_chat_id:
        token = settings.TELEGRAM_BOT_TOKEN
        app_url = settings.MINI_APP_URL
        sent = await send_single_notification(
            token=token,
            chat_id=target_chat_id,
            text=msg_text,
            image_url=first_image,
            button_text="🚀 Explore in Mini App",
            web_app_url=app_url,
            parse_mode="HTML"
        )
        return {
            "status": "success",
            "mode": "test_single_chat",
            "target_chat_id": target_chat_id,
            "delivered": sent,
            "events_count": len(selected_items),
            "titles": [it.get("event", {}).get("title") for it in selected_items]
        }

    # Otherwise, broadcast digest to all registered users
    result = await broadcast_to_all_users(
        text=msg_text,
        image_url=first_image,
        button_text="🚀 Explore in Mini App",
        parse_mode="HTML"
    )

    return {
        "status": "success",
        "mode": "broadcast_all",
        "broadcast_result": result,
        "events_count": len(selected_items),
        "titles": [it.get("event", {}).get("title") for it in selected_items]
    }
