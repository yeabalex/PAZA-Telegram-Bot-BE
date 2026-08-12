"""Notification Broadcaster Endpoints — Protected API routes for triggering broadcasts."""

import logging
import random
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.security import require_api_key
from app.services.bot.broadcaster import broadcast_to_all_users
from app.services.cache.redis_event_storage import RedisEventStorage

logger = logging.getLogger(__name__)
router = APIRouter()


def get_redis_storage() -> RedisEventStorage:
    return RedisEventStorage()


@router.post(
    "/broadcast-scraped",
    summary="Broadcast Random Recent Scraped Event from Redis to All Users",
    description="Picks a random recent active scraped event from Redis and broadcasts it to all users via Telegram Bot. Protected by X-Api-Key header.",
    dependencies=[Depends(require_api_key)]
)
async def broadcast_random_scraped_event(
    redis_storage: RedisEventStorage = Depends(get_redis_storage),
):
    """Fetches active scraped events from Redis, picks a random event, and broadcasts it to all registered users."""
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

    # Select a random active scraped event
    item = random.choice(raw_events)
    evt_data = item.get("event", {})
    post_id = item.get("post_id", "unknown")
    platform = item.get("platform", "ig")
    event_id = f"{platform}:{post_id}"

    title = evt_data.get("title") or "Upcoming Addis Social Event"
    venue = evt_data.get("venue_name") or "Addis Ababa"
    fee_raw = evt_data.get("entrance_fee_etb")
    fee_str = f"{float(fee_raw)} ETB" if fee_raw and float(fee_raw) > 0 else "FREE"
    cat_str = (evt_data.get("category") or "general").title()
    raw_desc = evt_data.get("description") or evt_data.get("short_summary") or "Check out this upcoming event in Addis Ababa!"
    desc = raw_desc[:140] + "..." if len(raw_desc) > 140 else raw_desc
    image_url = evt_data.get("image_url")

    msg_text = (
        f"⚡ **TRENDING EVENT DISCOVERY** 🎟️\n\n"
        f"📌 **{title}**\n"
        f"📍 **Venue**: {venue}\n"
        f"💰 **Entrance**: {fee_str}\n"
        f"🏷️ **Category**: #{cat_str}\n\n"
        f"{desc}\n\n"
        f"Tap below to explore events in Addis Ababa!"
    )

    result = await broadcast_to_all_users(
        text=msg_text,
        image_url=image_url,
        button_text="🚀 Explore in Mini App",
        mini_app_params=f"event_id={event_id}"
    )

    return {
        "status": "success",
        "broadcast_result": result,
        "event_id": event_id,
        "title": title
    }
