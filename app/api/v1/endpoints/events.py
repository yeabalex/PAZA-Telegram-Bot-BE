"""Event Endpoints Controller — Thin FastAPI Router delegating to EventRepository."""

import logging
import httpx
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import require_telegram_user
from app.db.session import get_db
from app.services.cache.redis_event_storage import RedisEventStorage
from app.services.event.event_repository import EventRepository
from app.services.storage import cloudinary_storage_service, r2_storage_service
from app.schemas.event import (
    CategoryInfo,
    EventDetailSchema,
    EventResponseSchema,
    EventSummarySchema,
    RsvpRequest,
    RsvpUserSchema,
    SaveScrapedEventRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()
redis_event_storage = RedisEventStorage()


# ════════════════════════════════════════════════════════════════════════════════
# PUBLIC READ ENDPOINTS (no auth required)
# ════════════════════════════════════════════════════════════════════════════════

@router.get(
    "/categories",
    response_model=List[CategoryInfo],
    summary="List available event categories with counts",
)
async def list_event_categories():
    """Returns categories that have at least one active event, sorted by count."""
    try:
        return await EventRepository.get_event_categories(redis_event_storage)
    except Exception as e:
        logger.error(f"Failed to fetch categories from Redis: {e}")
        return []


@router.get(
    "/explore",
    response_model=List[EventResponseSchema],
    summary="List Scraped Social Media Events (Explore Tab)",
    description="Fetches scraped Instagram/TikTok/Telegram events directly from Redis cache."
)
async def list_explore_scraped_events(
    category: Optional[str] = Query(None, description="Filter events by category slug"),
    skip: int = Query(0, ge=0, description="Number of events to skip"),
    limit: int = Query(7, ge=1, le=50, description="Max events per page"),
):
    """Returns scraped events from Redis cache for Explore tab, with pagination."""
    try:
        return await EventRepository.list_explore_scraped_events(
            redis_storage=redis_event_storage,
            category=category,
            skip=skip,
            limit=limit,
        )
    except Exception as e:
        logger.error(f"Failed to fetch explore events from Redis: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Redis cache service error: {str(e)}"
        )


@router.get(
    "/for-you",
    response_model=List[EventResponseSchema],
    summary="List Platform Organizer Events (For You Tab)",
    description="Fetches verified organizer-posted events from PostgreSQL filtered by user interests."
)
async def list_for_you_organizer_events(
    telegram_id: Optional[int] = Query(None, description="Telegram user ID"),
    category: Optional[str] = Query(None, description="Filter by category slug"),
    db: AsyncSession = Depends(get_db)
):
    """Returns verified platform organizer events from PostgreSQL for For You tab."""
    try:
        return await EventRepository.list_organizer_events(db=db, category=category)
    except Exception as e:
        logger.error(f"Failed to fetch organizer events from PostgreSQL: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"PostgreSQL database error: {str(e)}"
        )


@router.get(
    "",
    response_model=List[EventResponseSchema],
    summary="List All Active Events",
    description="Combines scraped events from Redis and platform events from PostgreSQL."
)
async def list_all_active_events(
    category: Optional[str] = Query(None, description="Filter by category slug"),
    db: AsyncSession = Depends(get_db)
):
    """Combines explore scraped events and organizer events."""
    scraped = await list_explore_scraped_events(category=category)
    organizer = await list_for_you_organizer_events(category=category, db=db)
    return scraped + organizer


@router.get(
    "/detail/{event_id:path}",
    response_model=EventDetailSchema,
    summary="Get Full Event Details",
    description="Fetches full details including description and images for a specific event ID."
)
async def get_event_detail(
    event_id: str,
    db: AsyncSession = Depends(get_db)
):
    detail = await EventRepository.get_event_detail(
        db=db, redis_storage=redis_event_storage, event_id=event_id
    )
    if detail:
        return detail

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event detail not found")


@router.get(
    "/verify-ticket",
    response_model=dict,
    summary="Verify Digital Entry Ticket Pass",
    description="Validates a ticket by event_id and ticket_code for door authentication."
)
async def verify_ticket(
    event_id: str = Query(...),
    ticket_code: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    try:
        return await EventRepository.verify_ticket(
            db=db,
            redis_storage=redis_event_storage,
            event_id=event_id,
            ticket_code=ticket_code
        )
    except Exception as e:
        logger.error(f"Error verifying ticket: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.get(
    "/rsvp",
    response_model=List[RsvpUserSchema],
    summary="List all RSVPs for an event",
)
async def list_rsvps(
    event_id: str = Query(...),
    db: AsyncSession = Depends(get_db)
):
    try:
        return await EventRepository.list_rsvps(db=db, event_id=event_id)
    except Exception as e:
        logger.error(f"Failed to list RSVPs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


# ════════════════════════════════════════════════════════════════════════════════
# PROTECTED USER-ACTION ENDPOINTS (Telegram initData required)
# ════════════════════════════════════════════════════════════════════════════════

@router.post(
    "/save-scraped",
    summary="Save Scraped Event to PostgreSQL DB",
    description="Stores a scraped event as raw JSON in permanent PostgreSQL storage for a user. Requires X-Telegram-Init-Data header."
)
async def save_scraped_event(
    payload: SaveScrapedEventRequest,
    tg_user: dict = Depends(require_telegram_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        # Use verified telegram_id from initData
        verified_tg_id = int(tg_user["id"])
        await EventRepository.save_scraped_event(
            db=db,
            telegram_id=verified_tg_id,
            event_id=payload.event_id,
            event_data=payload.event_data,
        )
        return {"status": "success", "message": "Scraped event saved to DB"}
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to save scraped event: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.delete(
    "/save-scraped",
    summary="Un-save Scraped Event from PostgreSQL DB",
    description="Requires X-Telegram-Init-Data header.",
)
async def remove_saved_scraped_event(
    event_id: str = Query(...),
    tg_user: dict = Depends(require_telegram_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        # Use verified telegram_id from initData
        verified_tg_id = int(tg_user["id"])
        removed = await EventRepository.remove_saved_scraped_event(
            db=db, telegram_id=verified_tg_id, event_id=event_id
        )
        if removed:
            return {"status": "success", "message": "Event removed from DB"}
        return {"status": "not_found", "message": "Event was not saved"}
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to remove saved scraped event: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.get(
    "/saved-scraped",
    response_model=List[dict],
    summary="Get User's Saved Scraped Events from PostgreSQL DB",
    description="Requires X-Telegram-Init-Data header.",
)
async def get_saved_scraped_events(
    tg_user: dict = Depends(require_telegram_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        verified_tg_id = int(tg_user["id"])
        return await EventRepository.get_saved_scraped_events(db=db, telegram_id=verified_tg_id)
    except Exception as e:
        logger.error(f"Failed to fetch saved scraped events: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.get(
    "/user-rsvps",
    response_model=List[dict],
    summary="Get User's RSVP'd Events from PostgreSQL DB",
    description="Requires X-Telegram-Init-Data header.",
)
async def get_user_rsvps(
    tg_user: dict = Depends(require_telegram_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        verified_tg_id = int(tg_user["id"])
        return await EventRepository.get_user_rsvps(db=db, redis_storage=redis_event_storage, telegram_id=verified_tg_id)
    except Exception as e:
        logger.error(f"Failed to fetch user rsvp events: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


# ════════════════════════════════════════════════════════════════════════════════
# RSVP ("Going") ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════════

@router.post(
    "/rsvp",
    summary="Mark user as Going to an event",
    description="Creates or updates an RSVP for the given event. Requires X-Telegram-Init-Data header.",
)
async def mark_going(
    body: RsvpRequest,
    tg_user: dict = Depends(require_telegram_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        await EventRepository.mark_rsvp(db=db, body=body)
        return {"status": "success", "message": "RSVP saved"}
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to save RSVP: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.delete(
    "/rsvp",
    summary="Remove user's RSVP from an event",
    description="Requires X-Telegram-Init-Data header.",
)
async def remove_going(
    event_id: str = Query(...),
    tg_user: dict = Depends(require_telegram_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        verified_tg_id = int(tg_user["id"])
        removed = await EventRepository.remove_rsvp(
            db=db, event_id=event_id, telegram_id=verified_tg_id
        )
        if removed:
            return {"status": "success", "message": "RSVP removed"}
        return {"status": "not_found", "message": "RSVP was not found"}
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to remove RSVP: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {str(e)}"
        )


@router.post(
    "/upload-receipt",
    summary="Upload RSVP Payment Receipt Screenshot",
    description="Uploads RSVP payment receipt screenshot to Cloudinary / R2 CDN. Requires X-Telegram-Init-Data header."
)
async def upload_rsvp_receipt(
    file: UploadFile = File(...),
    tg_user: dict = Depends(require_telegram_user),
):
    try:
        if cloudinary_storage_service._is_configured():
            url = await cloudinary_storage_service.upload_file(file=file, folder="paza/rsvps/receipts")
        else:
            url = await r2_storage_service.upload_file(file=file, folder="rsvps/receipts")
        return {"url": url}
    except Exception as e:
        logger.error(f"Error uploading RSVP receipt image: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload receipt screenshot: {str(e)}"
        )


@router.post(
    "/send-invite",
    summary="Send Event Invite with Artwork via Telegram Bot",
    description="Uploads generated invite artwork image and sends a photo message via Telegram bot to the invited user. Requires X-Telegram-Init-Data header."
)
async def send_event_invite(
    event_id: str = Form(...),
    inviter_name: str = Form(...),
    inviter_username: Optional[str] = Form(None),
    invitee_telegram_id: int = Form(...),
    invitee_username: Optional[str] = Form(None),
    vibe: Optional[str] = Form("casual"),
    image: Optional[UploadFile] = File(None),
    tg_user: dict = Depends(require_telegram_user),
    db: AsyncSession = Depends(get_db)
):
    try:
        import urllib.parse
        clean_id = urllib.parse.unquote(str(event_id)).strip()

        # 1. Fetch event details for title and venue
        evt_detail = await EventRepository.get_event_detail(db=db, redis_storage=redis_event_storage, event_id=clean_id)
        event_title = evt_detail.title if evt_detail else "Event"
        venue_name = evt_detail.venue_name if evt_detail else "Addis Ababa"

        # 2. Upload artwork image if provided
        image_url = None
        if image:
            try:
                if cloudinary_storage_service._is_configured():
                    image_url = await cloudinary_storage_service.upload_file(file=image, folder="paza/invites")
                else:
                    image_url = await r2_storage_service.upload_file(file=image, folder="invites")
            except Exception as upload_err:
                logger.error(f"Failed to upload invite artwork image: {upload_err}")

        # 3. Build WebApp Deep Link
        mini_app_url = settings.MINI_APP_URL.rstrip('/')
        event_link = f"{mini_app_url}/?event_id={urllib.parse.quote(clean_id)}"

        display_inviter = f"@{inviter_username}" if inviter_username else inviter_name

        vibe_emoji = "💖" if vibe == "date" else "🍻" if vibe == "hangout" else "✨"
        vibe_text = (
            "would love to go on a date with you to this event!" if vibe == "date"
            else "wants to hangout with you at this event!" if vibe == "hangout"
            else "invited you to check out this event!"
        )

        caption_text = (
            f"🎉 <b>{display_inviter}</b> {vibe_text} {vibe_emoji}\n\n"
            f"📍 <b>Event:</b> <b>{event_title}</b>\n"
            f"🏛️ <b>Venue:</b> {venue_name}\n\n"
            f"Tap the button below to view details and RSVP!"
        )

        bot_token = settings.TELEGRAM_BOT_TOKEN
        reply_markup = {
            "inline_keyboard": [
                [
                    {
                        "text": "✨ View Event & Join",
                        "web_app": {"url": event_link}
                    }
                ]
            ]
        }

        async with httpx.AsyncClient(timeout=12.0) as client:
            if image_url:
                tg_url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                payload = {
                    "chat_id": invitee_telegram_id,
                    "photo": image_url,
                    "caption": caption_text,
                    "parse_mode": "HTML",
                    "reply_markup": reply_markup
                }
                res = await client.post(tg_url, json=payload)
            else:
                tg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {
                    "chat_id": invitee_telegram_id,
                    "text": caption_text,
                    "parse_mode": "HTML",
                    "reply_markup": reply_markup
                }
                res = await client.post(tg_url, json=payload)

            if not res.is_success:
                logger.error(f"Telegram API sendPhoto/sendMessage failed ({res.status_code}): {res.text}")
                if "bot was blocked" in res.text or "chat not found" in res.text:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Cannot send message to @{invitee_username or invitee_telegram_id} — the user has not started @AddisEventBot on Telegram yet."
                    )
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Telegram notification error: {res.text}"
                )

        return {
            "status": "success",
            "message": f"Invite artwork sent to @{invitee_username or invitee_telegram_id} on Telegram!",
            "image_url": image_url
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error sending event invite: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send invite: {str(e)}"
        )
