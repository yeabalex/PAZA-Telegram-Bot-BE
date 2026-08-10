"""Event Repository Service — Encapsulates database and Redis operations for Events & RSVPs."""

import json
import logging
import uuid
from typing import List, Optional, Dict, Any
from sqlalchemy import select, func, delete
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Event, Interest, Organizer, SavedScrapedEvent, EventRsvp
from app.services.cache.redis_event_storage import RedisEventStorage
from app.services.event.event_utils import normalize_category_slug, geocode_venue_osm
from app.schemas.event import (
    CategoryInfo,
    EventSummarySchema,
    EventDetailSchema,
    RsvpRequest,
    RsvpUserSchema,
)
from app.schemas.organizer import OrganizerEventCreate, OrganizerEventUpdate

logger = logging.getLogger(__name__)

CATEGORY_LABELS = {
    "music": "Music & Concerts",
    "nightlife": "Nightlife & Parties",
    "tech": "Tech & Software",
    "business": "Business & Entrepreneurship",
    "art": "Arts, Exhibition & Culture",
    "food": "Food, Coffee & Dining",
    "cinema": "Movies, Cinema & Theater",
    "sports": "Sports, Gaming & Esports",
    "fitness": "Fitness, Health & Wellness",
    "outdoor": "Outdoors, Travel & Hiking",
    "education": "Education, Workshops & Training",
    "fashion": "Fashion, Beauty & Modeling",
    "bazaars": "Bazaars, Expos & Trade Fairs",
    "community": "Community, Networking & Meetups",
    "charity": "Charity, Non-Profit & Social Causes",
    "kids": "Kids, Family & Youth",
    "realestate": "Real Estate, Architecture & Design",
    "science": "Science, Innovation & Research",
    "books": "Books, Literature & Poetry",
    "faith": "Religious, Spiritual & Faith",
    "government": "Government, Policy & Law",
    "general": "Other / General",
}


class EventRepository:
    """Repository class encapsulating Event data access across Redis cache and PostgreSQL DB."""

    @staticmethod
    async def get_event_categories(redis_storage: RedisEventStorage) -> List[CategoryInfo]:
        """Aggregate available event categories with active counts from Redis."""
        raw_events = await redis_storage.get_all_active_events()
        category_counts: Dict[str, int] = {}

        for item in raw_events:
            evt_data = item.get("event", {})
            raw_cat = evt_data.get("category") or "general"
            slug = normalize_category_slug(raw_cat)
            category_counts[slug] = category_counts.get(slug, 0) + 1

        results = [
            CategoryInfo(slug=slug, label=CATEGORY_LABELS.get(slug, slug.title()), count=count)
            for slug, count in category_counts.items()
        ]
        results.sort(key=lambda c: c.count, reverse=True)
        return results

    @staticmethod
    async def list_explore_scraped_events(
        redis_storage: RedisEventStorage,
        category: Optional[str] = None,
        skip: int = 0,
        limit: int = 7,
    ) -> List[EventSummarySchema]:
        """Fetch scraped events from Redis cache for Explore tab with pagination and filtering."""
        raw_events = await redis_storage.get_all_active_events()
        results: List[EventSummarySchema] = []

        for item in raw_events:
            evt_data = item.get("event", {})
            raw_cat = evt_data.get("category") or "general"
            cat_slug = normalize_category_slug(raw_cat)

            if category and category != "all":
                filter_cat = category.lower().strip()
                if filter_cat != cat_slug and filter_cat not in str(raw_cat).lower():
                    continue

            post_id = item.get("post_id", "unknown")
            platform = item.get("platform", "ig")
            desc = (
                evt_data.get("description")
                or evt_data.get("short_summary")
                or item.get("metadata", {}).get("raw_caption")
                or ""
            )

            results.append(
                EventSummarySchema(
                    id=f"{platform}:{post_id}",
                    title=evt_data.get("title") or "Upcoming Addis Social Event",
                    description=desc,
                    venue_name=evt_data.get("venue_name") or "Addis Ababa",
                    sub_city=evt_data.get("sub_city"),
                    start_datetime=evt_data.get("start_datetime"),
                    entrance_fee_etb=evt_data.get("entrance_fee_etb") or 0.0,
                    category=cat_slug,
                    source_type="scraped",
                )
            )

        return results[skip : skip + limit]

    @staticmethod
    async def list_organizer_events(
        db: AsyncSession,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> List[EventSummarySchema]:
        """Fetch organizer events from PostgreSQL for For You tab, with organizer verification info."""
        stmt = (
            select(Event, Organizer)
            .outerjoin(Organizer, Event.organizer_id == Organizer.id)
        )
        if category and category != "all":
            stmt = stmt.join(Interest, Event.interest_id == Interest.id).where(
                Interest.slug == category.lower()
            )

        stmt = stmt.order_by(Event.start_time.desc()).limit(limit)
        res = await db.execute(stmt)
        rows = res.all()

        # Cache organizer total event counts
        org_event_counts: dict = {}

        results: List[EventSummarySchema] = []
        for evt, org in rows:
            org_id = str(org.id) if org else None
            org_events_cnt = 0
            if org_id:
                if org_id not in org_event_counts:
                    cnt_stmt = select(func.count()).select_from(Event).where(Event.organizer_id == org.id)
                    cnt_res = await db.execute(cnt_stmt)
                    org_event_counts[org_id] = cnt_res.scalar() or 0
                org_events_cnt = org_event_counts[org_id]

            results.append(
                EventSummarySchema(
                    id=str(evt.id),
                    title=evt.title,
                    short_description=evt.short_description,
                    description=evt.description,
                    venue_name=evt.venue_name or "Addis Ababa",
                    sub_city=evt.sub_city,
                    start_datetime=evt.start_time.isoformat() if evt.start_time else None,
                    entrance_fee_etb=float(evt.price_etb) if evt.price_etb else 0.0,
                    category="general",
                    image_url=evt.image_url or "",
                    rsvp_count=evt.rsvp_count or 0,
                    max_capacity=100,
                    source_type="organizer",
                    organizer_name=org.org_name if org else "Unknown Organizer",
                    organizer_username=org.username if org else None,
                    organizer_logo=org.logo_url if org else None,
                    is_organizer_verified=bool(org.is_verified) if org else False,
                    organizer_events_count=org_events_cnt,
                )
            )
        return results

    @staticmethod
    async def get_event_detail(
        db: AsyncSession,
        redis_storage: RedisEventStorage,
        event_id: str,
    ) -> Optional[EventDetailSchema]:
        """Fetch event details across Redis, saved scraped table, or organizer DB table."""
        import urllib.parse
        clean_id = urllib.parse.unquote(event_id).strip()

        # 1. Check Redis for scraped events
        try:
            raw_events = await redis_storage.get_all_active_events()
            for item in raw_events:
                post_id = str(item.get("post_id", "unknown"))
                platform = str(item.get("platform", "ig"))
                full_id = f"{platform}:{post_id}"

                if full_id == clean_id or post_id == clean_id:
                    evt_data = item.get("event", {})
                    raw_cat = evt_data.get("category") or "general"

                    # Count RSVPs
                    rsvp_stmt = (
                        select(func.count())
                        .select_from(EventRsvp)
                        .where(EventRsvp.event_id == full_id)
                    )
                    rsvp_res = await db.execute(rsvp_stmt)
                    real_rsvp_count = rsvp_res.scalar() or 0

                    location_gps = evt_data.get("location_gps") or "9.0320,38.7478"
                    desc = (
                        evt_data.get("description")
                        or evt_data.get("short_summary")
                        or item.get("metadata", {}).get("raw_caption")
                        or "Event happening in Addis Ababa."
                    )

                    fee_raw = evt_data.get("entrance_fee_etb")
                    fee_val = float(fee_raw) if fee_raw is not None else 0.0

                    return EventDetailSchema(
                        id=full_id,
                        title=evt_data.get("title", "Untitled Event"),
                        description=desc,
                        venue_name=evt_data.get("venue_name", "Addis Ababa"),
                        sub_city=evt_data.get("sub_city", ""),
                        start_datetime=evt_data.get("start_datetime"),
                        end_datetime=evt_data.get("end_datetime"),
                        entrance_fee_etb=fee_val,
                        category=raw_cat.lower(),
                        image_url=evt_data.get("image_url", ""),
                        location_gps=location_gps,
                        rsvp_count=real_rsvp_count,
                        source_type="scraped",
                    )
        except Exception as e:
            logger.error(f"Error reading Redis event detail: {e}")

        # 2. Check saved scraped events table
        try:
            stmt = select(SavedScrapedEvent).where(SavedScrapedEvent.event_id == clean_id)
            res = await db.execute(stmt)
            saved = res.scalar_one_or_none()
            if saved:
                data = saved.event_data or {}
                rsvp_stmt = (
                    select(func.count())
                    .select_from(EventRsvp)
                    .where(EventRsvp.event_id == clean_id)
                )
                rsvp_res = await db.execute(rsvp_stmt)
                real_rsvp_count = rsvp_res.scalar() or 0

                desc = (
                    data.get("description")
                    or data.get("short_summary")
                    or "Event happening in Addis Ababa."
                )

                s_fee_raw = data.get("entrance_fee_etb")
                s_fee_val = float(s_fee_raw) if s_fee_raw is not None else 0.0

                return EventDetailSchema(
                    id=clean_id,
                    title=data.get("title", "Untitled Event"),
                    description=desc,
                    venue_name=data.get("venue_name", "Addis Ababa"),
                    sub_city=data.get("sub_city", ""),
                    start_datetime=data.get("start_datetime"),
                    end_datetime=data.get("end_datetime"),
                    entrance_fee_etb=s_fee_val,
                    category=(data.get("category") or "general").lower(),
                    image_url=data.get("image_url", ""),
                    rsvp_count=real_rsvp_count,
                    source_type="scraped",
                )
        except Exception as e:
            logger.error(f"Error reading DB saved event detail: {e}")

        # 3. Check organizer events DB table (only if clean_id is a valid UUID)
        try:
            val_uuid = uuid.UUID(clean_id)
        except (ValueError, AttributeError, TypeError):
            return None

        try:
            stmt = (
                select(Event, Organizer)
                .outerjoin(Organizer, Event.organizer_id == Organizer.id)
                .where(Event.id == val_uuid)
            )
            res = await db.execute(stmt)
            row = res.one_or_none()
            if row:
                evt, org = row
                org_evt_id = str(evt.id)
                rsvp_stmt = (
                    select(func.count())
                    .select_from(EventRsvp)
                    .where(EventRsvp.event_id == org_evt_id)
                )
                rsvp_res = await db.execute(rsvp_stmt)
                real_rsvp_count = rsvp_res.scalar() or 0

                org_events_cnt = 0
                t_phone, t_name, c_acc, c_name = None, None, None, None
                if org:
                    cnt_stmt = select(func.count()).select_from(Event).where(Event.organizer_id == org.id)
                    cnt_res = await db.execute(cnt_stmt)
                    org_events_cnt = cnt_res.scalar() or 0

                    payout_raw = getattr(org, "payout_bank_details", None)
                    if payout_raw:
                        try:
                            parsed = json.loads(payout_raw)
                            if isinstance(parsed, dict):
                                t_phone = parsed.get("telebirr_phone")
                                t_name = parsed.get("telebirr_name")
                                c_acc = parsed.get("cbe_account")
                                c_name = parsed.get("cbe_name")
                        except Exception:
                            pass

                return EventDetailSchema(
                    id=org_evt_id,
                    title=evt.title,
                    description=evt.description,
                    venue_name=evt.venue_name or "Addis Ababa",
                    sub_city=evt.sub_city,
                    start_datetime=evt.start_time.isoformat() if evt.start_time else None,
                    end_datetime=evt.end_time.isoformat() if evt.end_time else None,
                    entrance_fee_etb=float(evt.price_etb) if evt.price_etb else 0.0,
                    category="general",
                    image_url=evt.image_url or "",
                    rsvp_count=real_rsvp_count,
                    source_type="organizer",
                    organizer_name=org.org_name if org else "Unknown Organizer",
                    organizer_username=org.username if org else None,
                    organizer_logo=org.logo_url if org else None,
                    is_organizer_verified=bool(org.is_verified) if org else False,
                    organizer_events_count=org_events_cnt,
                    telebirr_phone=t_phone,
                    telebirr_name=t_name,
                    cbe_account=c_acc,
                    cbe_name=c_name,
                )
        except Exception as e:
            logger.error(f"Error reading DB organizer event detail: {e}")

        return None

    @staticmethod
    async def save_scraped_event(
        db: AsyncSession,
        telegram_id: int,
        event_id: str,
        event_data: dict,
    ) -> bool:
        """Save raw scraped event JSON for user."""
        stmt = select(SavedScrapedEvent).where(
            SavedScrapedEvent.telegram_id == telegram_id,
            SavedScrapedEvent.event_id == event_id,
        )
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing:
            existing.event_data = event_data
        else:
            saved_item = SavedScrapedEvent(
                telegram_id=telegram_id, event_id=event_id, event_data=event_data
            )
            db.add(saved_item)

        await db.commit()
        return True

    @staticmethod
    async def remove_saved_scraped_event(
        db: AsyncSession,
        telegram_id: int,
        event_id: str,
    ) -> bool:
        """Remove saved scraped event for user."""
        stmt = select(SavedScrapedEvent).where(
            SavedScrapedEvent.telegram_id == telegram_id,
            SavedScrapedEvent.event_id == event_id,
        )
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing:
            await db.delete(existing)
            await db.commit()
            return True
        return False

    @staticmethod
    async def get_saved_scraped_events(
        db: AsyncSession,
        telegram_id: int,
    ) -> List[dict]:
        """Fetch all saved scraped event JSONs for user."""
        stmt = (
            select(SavedScrapedEvent)
            .where(SavedScrapedEvent.telegram_id == telegram_id)
            .order_by(SavedScrapedEvent.created_at.desc())
        )
        res = await db.execute(stmt)
        items = res.scalars().all()
        return [item.event_data for item in items]

    @staticmethod
    async def mark_rsvp(db: AsyncSession, body: RsvpRequest) -> bool:
        """Upsert user RSVP for an event."""
        stmt = select(EventRsvp).where(
            EventRsvp.telegram_id == body.telegram_id,
            EventRsvp.event_id == body.event_id,
        )
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing:
            existing.first_name = body.first_name
            existing.full_name = body.full_name
            existing.username = body.username
            existing.photo_url = body.photo_url
            existing.message = body.message
            existing.transaction_id = body.transaction_id
            existing.screenshot_url = body.screenshot_url
            existing.payment_method = body.payment_method
        else:
            rsvp = EventRsvp(
                event_id=body.event_id,
                telegram_id=body.telegram_id,
                first_name=body.first_name,
                full_name=body.full_name,
                username=body.username,
                photo_url=body.photo_url,
                message=body.message,
                transaction_id=body.transaction_id,
                screenshot_url=body.screenshot_url,
                payment_method=body.payment_method,
            )
            db.add(rsvp)

        await db.commit()
        return True

    @staticmethod
    async def remove_rsvp(
        db: AsyncSession,
        event_id: str,
        telegram_id: int,
    ) -> bool:
        """Remove RSVP for an event."""
        import urllib.parse
        clean_id = urllib.parse.unquote(str(event_id)).strip()
        stmt = select(EventRsvp).where(
            EventRsvp.telegram_id == telegram_id,
            EventRsvp.event_id.in_([clean_id, str(event_id)]),
        )
        res = await db.execute(stmt)
        existing = res.scalar_one_or_none()

        if existing:
            await db.delete(existing)
            await db.commit()
            return True
        return False

    @staticmethod
    async def list_rsvps(db: AsyncSession, event_id: str) -> List[RsvpUserSchema]:
        """List all user RSVPs for an event."""
        import urllib.parse
        clean_id = urllib.parse.unquote(str(event_id)).strip()
        stmt = (
            select(
                EventRsvp.telegram_id,
                EventRsvp.first_name,
                EventRsvp.full_name,
                EventRsvp.username,
                EventRsvp.photo_url,
                EventRsvp.message,
                EventRsvp.transaction_id,
                EventRsvp.screenshot_url,
                EventRsvp.payment_method,
                EventRsvp.ticket_code,
                EventRsvp.status,
                EventRsvp.created_at,
            )
            .where(EventRsvp.event_id.in_([clean_id, str(event_id)]))
            .order_by(EventRsvp.created_at.desc())
        )
        res = await db.execute(stmt)
        rows = res.all()
        return [
            RsvpUserSchema(
                telegram_id=r[0],
                first_name=r[1],
                full_name=r[2],
                username=r[3],
                photo_url=r[4],
                message=r[5],
                transaction_id=r[6],
                screenshot_url=r[7],
                payment_method=r[8],
                ticket_code=r[9],
                status=r[10] or "pending",
                created_at=r[11].isoformat() if r[11] else None,
            )
            for r in rows
        ]

    @staticmethod
    async def confirm_rsvp(
        db: AsyncSession,
        redis_storage: RedisEventStorage,
        event_id: str,
        telegram_id: int,
    ) -> Optional[dict]:
        """Confirm attendee RSVP, generate ticket code, and send Telegram notification via bot."""
        import urllib.parse
        import random
        import string
        import httpx

        clean_id = urllib.parse.unquote(str(event_id)).strip()
        stmt = select(EventRsvp).where(
            EventRsvp.telegram_id == telegram_id,
            EventRsvp.event_id.in_([clean_id, str(event_id)]),
        )
        res = await db.execute(stmt)
        rsvp = res.scalar_one_or_none()

        if not rsvp:
            return None

        # Generate ticket code if not present
        if not rsvp.ticket_code:
            rand_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
            rsvp.ticket_code = f"TK-{rand_code}"

        rsvp.status = "confirmed"
        await db.commit()

        # Fetch event title for Telegram message
        evt_detail = await EventRepository.get_event_detail(db=db, redis_storage=redis_storage, event_id=clean_id)
        event_title = evt_detail.title if evt_detail else "Event"

        # Build verification URL
        mini_app_url = settings.MINI_APP_URL.rstrip('/')
        verify_url = f"{mini_app_url}/?verify_event_id={clean_id}&ticket_code={rsvp.ticket_code}"

        # Send Telegram Bot Message
        try:
            bot_token = settings.TELEGRAM_BOT_TOKEN
            msg_text = (
                f"<b>PAZA EVENTS — ATTENDANCE CONFIRMED!</b>\n\n"
                f"🎉 Your registration for <b>{event_title}</b> has been approved by the organizer!\n\n"
                f"🎫 <b>Ticket Pass Code:</b> <code>{rsvp.ticket_code}</code>\n\n"
                f"Tap the button below to view your digital ticket pass for entry authentication at the door."
            )
            tg_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {
                "chat_id": telegram_id,
                "text": msg_text,
                "parse_mode": "HTML",
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {
                                "text": "🎫 View Entry Ticket Pass",
                                "web_app": {"url": verify_url}
                            }
                        ]
                    ]
                }
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                res = await client.post(tg_url, json=payload)
                if res.is_success:
                    logger.info(f"Successfully sent Telegram ticket message to user [{telegram_id}]")
                else:
                    logger.error(f"Telegram API error ({res.status_code}) sending ticket to [{telegram_id}]: {res.text}")
        except Exception as e:
            logger.error(f"Failed to send Telegram ticket message to {telegram_id}: {e}")

        return {
            "ticket_code": rsvp.ticket_code,
            "status": rsvp.status,
            "message": "Attendance confirmed and Telegram ticket sent."
        }

    @staticmethod
    async def verify_ticket(
        db: AsyncSession,
        redis_storage: RedisEventStorage,
        event_id: str,
        ticket_code: str,
    ) -> dict:
        """Verify an event ticket by event_id and ticket_code."""
        import urllib.parse
        clean_id = urllib.parse.unquote(str(event_id)).strip()
        clean_code = str(ticket_code).strip()

        stmt = select(EventRsvp).where(
            EventRsvp.event_id.in_([clean_id, str(event_id)]),
            EventRsvp.ticket_code == clean_code
        )
        res = await db.execute(stmt)
        rsvp = res.scalar_one_or_none()

        if not rsvp:
            return {"valid": False, "message": "Ticket not found or invalid code."}

        evt_detail = await EventRepository.get_event_detail(db=db, redis_storage=redis_storage, event_id=clean_id)
        event_title = evt_detail.title if evt_detail else "Event"
        venue_name = evt_detail.venue_name if evt_detail else "Addis Ababa"

        return {
            "valid": True,
            "status": rsvp.status or "confirmed",
            "ticket_code": rsvp.ticket_code,
            "event_id": clean_id,
            "event_title": event_title,
            "venue_name": venue_name,
            "attendee_name": rsvp.full_name or rsvp.first_name,
            "first_name": rsvp.first_name,
            "username": rsvp.username,
            "telegram_id": rsvp.telegram_id,
            "photo_url": rsvp.photo_url,
            "payment_method": rsvp.payment_method,
            "transaction_id": rsvp.transaction_id,
            "confirmed_at": rsvp.created_at.isoformat() if rsvp.created_at else None,
        }

    @staticmethod
    async def get_user_rsvps(
        db: AsyncSession,
        redis_storage: RedisEventStorage,
        telegram_id: int,
    ) -> List[dict]:
        """Fetch all events that the specified telegram_id user has RSVP'd to."""
        stmt = (
            select(EventRsvp.event_id)
            .where(EventRsvp.telegram_id == telegram_id)
            .order_by(EventRsvp.created_at.desc())
        )
        res = await db.execute(stmt)
        event_ids = [r[0] for r in res.all()]

        events = []
        for eid in event_ids:
            evt_detail = await EventRepository.get_event_detail(db=db, redis_storage=redis_storage, event_id=eid)
            if evt_detail:
                events.append(evt_detail.model_dump())
        return events

    @staticmethod
    async def get_organizer_event(
        db: AsyncSession,
        organizer_id: uuid.UUID,
        event_id: uuid.UUID,
    ) -> Optional[Event]:
        """Fetch a single event scoped to an organizer (ownership check)."""
        stmt = select(Event).where(
            Event.id == event_id,
            Event.organizer_id == organizer_id,
        )
        res = await db.execute(stmt)
        return res.scalar_one_or_none()

    @staticmethod
    async def list_organizer_owned_events(
        db: AsyncSession,
        organizer_id: uuid.UUID
    ) -> List[Event]:
        """Fetch all events created by specific organizer ID sorted by start_time descending."""
        stmt = (
            select(Event)
            .options(joinedload(Event.interest), joinedload(Event.organizer))
            .where(Event.organizer_id == organizer_id)
            .order_by(Event.start_time.desc())
        )
        res = await db.execute(stmt)
        return list(res.scalars().all())

    @staticmethod
    async def create_organizer_event(
        db: AsyncSession,
        organizer_id: uuid.UUID,
        data: OrganizerEventCreate
    ) -> Event:
        """Create new event for organizer."""
        try:
            interest_id = None
            if data.category_slug and data.category_slug.strip():
                slug = normalize_category_slug(data.category_slug)
                stmt = select(Interest).where(Interest.slug == slug)
                res = await db.execute(stmt)
                interest = res.scalar_one_or_none()
                if interest:
                    interest_id = interest.id

            event = Event(
                organizer_id=organizer_id,
                interest_id=interest_id,
                title=data.title.strip(),
                short_description=data.short_description.strip() if data.short_description else None,
                description=data.description.strip() if data.description else None,
                start_time=data.start_time,
                end_time=data.end_time,
                venue_name=data.venue_name.strip() if data.venue_name else None,
                sub_city=data.sub_city.strip() if data.sub_city else None,
                location_gps=data.location_gps.strip() if data.location_gps else None,
                price_etb=data.price_etb,
                image_url=data.image_url.strip() if data.image_url else None,
                rsvp_count=0
            )
            db.add(event)
            await db.commit()

            stmt_event = select(Event).options(joinedload(Event.interest)).where(Event.id == event.id)
            res_event = await db.execute(stmt_event)
            return res_event.scalar_one()
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def update_organizer_event(
        db: AsyncSession,
        event_id: uuid.UUID,
        organizer_id: uuid.UUID,
        data: OrganizerEventUpdate
    ) -> Optional[Event]:
        """Update existing organizer event."""
        try:
            stmt = select(Event).where(Event.id == event_id, Event.organizer_id == organizer_id)
            res = await db.execute(stmt)
            event = res.scalar_one_or_none()
            if not event:
                return None

            if data.title is not None:
                event.title = data.title.strip()
            if data.short_description is not None:
                event.short_description = data.short_description.strip() if data.short_description else None
            if data.description is not None:
                event.description = data.description.strip() if data.description else None
            if data.start_time is not None:
                event.start_time = data.start_time
            if data.end_time is not None:
                event.end_time = data.end_time
            if data.venue_name is not None:
                event.venue_name = data.venue_name.strip() if data.venue_name else None
            if data.sub_city is not None:
                event.sub_city = data.sub_city.strip() if data.sub_city else None
            if data.location_gps is not None:
                event.location_gps = data.location_gps.strip() if data.location_gps else None
            if data.price_etb is not None:
                event.price_etb = data.price_etb
            if data.image_url is not None:
                event.image_url = data.image_url.strip() if data.image_url else None
            if data.category_slug is not None:
                if data.category_slug.strip():
                    slug = normalize_category_slug(data.category_slug)
                    stmt_cat = select(Interest).where(Interest.slug == slug)
                    res_cat = await db.execute(stmt_cat)
                    interest = res_cat.scalar_one_or_none()
                    if interest:
                        event.interest_id = interest.id
                else:
                    event.interest_id = None

            await db.commit()

            stmt_event = select(Event).options(joinedload(Event.interest)).where(Event.id == event.id)
            res_event = await db.execute(stmt_event)
            return res_event.scalar_one()
        except Exception:
            await db.rollback()
            raise

    @staticmethod
    async def delete_organizer_event(
        db: AsyncSession,
        event_id: uuid.UUID,
        organizer_id: uuid.UUID
    ) -> bool:
        """Delete an event owned by organizer."""
        stmt = select(Event).where(Event.id == event_id, Event.organizer_id == organizer_id)
        res = await db.execute(stmt)
        event = res.scalar_one_or_none()
        if event:
            await db.delete(event)
            await db.commit()
            return True
        return False

