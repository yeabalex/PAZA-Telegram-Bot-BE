"""Notification Broadcaster Endpoints — Protected API routes for triggering broadcasts."""

import html
import logging
from datetime import datetime
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


def format_event_datetime(dt_str: Optional[str]) -> Optional[str]:
    """Format ISO datetime string into human readable 'Thu, Aug 28 • 06:00 PM' format."""
    if not dt_str:
        return None
    try:
        clean_str = dt_str.replace("Z", "+00:00").replace(" ", "T")
        dt = datetime.fromisoformat(clean_str)
        return dt.strftime("%a, %b %d • %I:%M %p")
    except Exception:
        return str(dt_str)


@router.post(
    "/broadcast-scraped",
    summary="Broadcast Latest Extracted Event from Redis",
    description="Picks the latest extracted active event from Redis, formats it into a clean announcement card, and sends to target_chat_id or broadcasts to all registered users.",
    dependencies=[Depends(require_api_key)]
)
async def broadcast_scraped_events(
    limit: int = Query(1, ge=1, le=5, description="Number of latest events to inspect (broadcasts the top latest event)"),
    target_chat_id: Optional[int] = Query(None, description="Optional Telegram Chat ID to test sending to a single user/admin before broadcasting to all"),
    redis_storage: RedisEventStorage = Depends(get_redis_storage),
):
    """Fetches active scraped events from Redis, picks the latest event, and sends a polished announcement."""
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
    item = selected_items[0]

    evt_data = item.get("event", {}) if isinstance(item.get("event"), dict) else item

    raw_title = evt_data.get("title") or "Upcoming Addis Social Event"
    title = html.escape(raw_title.strip())

    venue_raw = evt_data.get("venue_name") or "Addis Ababa"
    sub_city = evt_data.get("sub_city")
    if sub_city and sub_city.strip() and sub_city.lower() not in venue_raw.lower():
        venue_display = f"{venue_raw}, {sub_city}"
    else:
        venue_display = venue_raw
    venue = html.escape(venue_display)

    fee_raw = evt_data.get("entrance_fee_etb")
    fee_str = f"{float(fee_raw):.0f} ETB" if fee_raw and float(fee_raw) > 0 else "FREE"

    date_str = format_event_datetime(evt_data.get("start_datetime"))

    raw_desc = evt_data.get("description") or evt_data.get("short_summary") or "Check out this upcoming event happening in Addis Ababa!"
    raw_desc = raw_desc.strip()
    if len(raw_desc) > 220:
        truncated = raw_desc[:220].rsplit(" ", 1)[0]
        desc_clean = html.escape(truncated) + "..."
    else:
        desc_clean = html.escape(raw_desc)

    # Build clean single-event announcement message
    lines = [
        "✨ <b>NEW EVENT IN ADDIS ABABA!</b> 🎟️\n",
        f"📌 <b>{title}</b>\n",
    ]
    if date_str:
        lines.append(f"📅 <b>Date</b>: {date_str}")
    lines.append(f"📍 <b>Venue</b>: {venue}")
    lines.append(f"💰 <b>Entrance</b>: {fee_str}\n")
    lines.append(f"📝 {desc_clean}\n")
    lines.append("<i>Tap below to view details & RSVP in PAZA Mini App!</i>")

    msg_text = "\n".join(lines)

    # Resolve event ID and image
    platform = item.get("platform") or item.get("source_platform") or evt_data.get("source_platform") or "tg"
    post_id = item.get("post_id") or item.get("source_message_id") or evt_data.get("source_message_id") or "1"
    event_id = f"{platform}:{post_id}" if not str(item.get("event_id", "")).startswith(f"{platform}:") else item.get("event_id")

    image_url = evt_data.get("image_url") or item.get("image_url")
    mini_app_params = f"event_id={event_id}"

    # If target_chat_id is provided, send test notification to that specific admin/chat ID only
    if target_chat_id:
        token = settings.TELEGRAM_BOT_TOKEN
        app_url = f"{settings.MINI_APP_URL.rstrip('/')}/?{mini_app_params}" if mini_app_params else settings.MINI_APP_URL
        sent = await send_single_notification(
            token=token,
            chat_id=target_chat_id,
            text=msg_text,
            image_url=image_url,
            button_text="🚀 View Event in Mini App",
            web_app_url=app_url,
            parse_mode="HTML"
        )
        return {
            "status": "success",
            "mode": "test_single_chat",
            "target_chat_id": target_chat_id,
            "delivered": sent,
            "event_title": raw_title,
            "event_id": event_id
        }

    # Otherwise, broadcast notification to all registered users
    result = await broadcast_to_all_users(
        text=msg_text,
        image_url=image_url,
        button_text="🚀 View Event in Mini App",
        mini_app_params=mini_app_params,
        parse_mode="HTML"
    )

    return {
        "status": "success",
        "mode": "broadcast_all",
        "broadcast_result": result,
        "event_title": raw_title,
        "event_id": event_id
    }
