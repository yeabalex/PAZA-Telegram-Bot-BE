"""User Authentication, Profile & Interest Management API Endpoints with Swagger OpenAPI Documentation."""

import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import require_api_key, require_telegram_user, verify_telegram_init_data
from app.db.session import get_db
from app.schemas.user import (
    BotStartRequest,
    InterestSchema,
    InterestSelectionRequest,
    PhoneNumberUpdateRequest,
    UserProfileSchema,
)
from app.services.user.user_repository import UserRepository

from app.services.bot.admin_notifier import notify_admin

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get(
    "/me",
    response_model=UserProfileSchema,
    summary="Get Current User Profile & Registration Status",
    description="Authenticates WebApp initData or telegram_id, auto-provisions user in PostgreSQL if missing, and returns user profile."
)
async def get_current_user_profile(
    telegram_id: Optional[int] = Query(None, description="Telegram numeric User ID (dev mode)"),
    init_data: Optional[str] = Query(None, description="Telegram WebApp initData string"),
    username: Optional[str] = Query(None, description="Telegram username for dev/client sync"),
    full_name: Optional[str] = Query(None, description="Telegram full name for dev/client sync"),
    db: AsyncSession = Depends(get_db)
):
    """Verifies Telegram WebApp initData/ID, auto-creates or syncs updated user in DB, and returns profile."""
    target_tg_id = telegram_id
    sync_full_name = full_name
    sync_username = username
    pref_lang = "en"
    has_tg_payload = False

    # Verify Telegram WebApp initData if provided
    if init_data:
        bot_token = settings.TELEGRAM_BOT_TOKEN
        tg_user = verify_telegram_init_data(init_data, bot_token)
        if tg_user and "id" in tg_user:
            target_tg_id = int(tg_user["id"])
            first_name = tg_user.get("first_name", "")
            last_name = tg_user.get("last_name", "")
            sync_full_name = f"{first_name} {last_name}".strip() or tg_user.get("username")
            sync_username = tg_user.get("username") or None
            pref_lang = tg_user.get("language_code", "en")
            has_tg_payload = True
    elif username or full_name:
        has_tg_payload = True

    if not target_tg_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing telegram_id or valid initData"
        )

    try:
        existing_user = await UserRepository.get_by_telegram_id(db, target_tg_id)
        is_new_user = existing_user is None

        # Auto-create or sync existing user profile with latest data from Telegram
        user = await UserRepository.get_or_create_user(
            db=db,
            telegram_id=target_tg_id,
            full_name=sync_full_name,
            username=sync_username,
            preferred_language=pref_lang,
            force_sync=has_tg_payload
        )

        if is_new_user:
            total_users = await UserRepository.get_total_users_count(db)
            uname_str = f"@{sync_username}" if sync_username else "None"
            user_link = f"tg://user?id={target_tg_id}"
            admin_msg = (
                f"🚀 **User Opened Mini App (New Registration)**\n\n"
                f"👤 **Name**: {sync_full_name or 'Anonymous'}\n"
                f"🏷️ **Username**: {uname_str}\n"
                f"🆔 **Telegram ID**: `{target_tg_id}`\n"
                f"🔗 **Profile Link**: [{sync_full_name or 'User Profile'}]({user_link})\n\n"
                f"📊 **Total Registered Users**: `{total_users}`"
            )
            await notify_admin(admin_msg)

        profile = await UserRepository.get_user_profile(db, user.telegram_id)
    except Exception as e:
        logger.error(f"Database error fetching/provisioning profile for tg_id={target_tg_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database temporarily unavailable. Please try again."
        )

    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Failed to retrieve user profile."
        )

    return profile


@router.post(
    "/bot-start",
    response_model=UserProfileSchema,
    summary="Bot /start Registration Initializer",
    description="Called by Telegram Bot when user sends /start. Creates or fetches user profile in PostgreSQL. Requires X-Api-Key header.",
    dependencies=[Depends(require_api_key)],
)
async def bot_start_register(
    req: BotStartRequest,
    db: AsyncSession = Depends(get_db)
):
    """Creates or updates user profile upon bot /start."""
    user = await UserRepository.get_or_create_user(
        db=db,
        telegram_id=req.telegram_id,
        full_name=req.full_name,
        username=req.username,
        preferred_language=req.preferred_language
    )

    profile = await UserRepository.get_user_profile(db, user.telegram_id)
    return profile


@router.post(
    "/phone-number",
    response_model=UserProfileSchema,
    summary="Update User Phone Number (Bot Contact Share)",
    description="Updates user's phone number when they share their contact button in Telegram Bot. Requires X-Api-Key header.",
    dependencies=[Depends(require_api_key)],
)
async def update_phone_number(
    req: PhoneNumberUpdateRequest,
    db: AsyncSession = Depends(get_db)
):
    """Updates user phone number upon sharing contact."""
    user = await UserRepository.update_phone_number(db, req.telegram_id, req.phone_number)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Please send /start first."
        )

    profile = await UserRepository.get_user_profile(db, req.telegram_id)
    return profile


@router.get(
    "/interests",
    response_model=List[InterestSchema],
    summary="List All Available Normalized Interests",
    description="Returns all normalized categories/interests for selection in Mini App."
)
async def list_all_interests(db: AsyncSession = Depends(get_db)):
    """Returns list of all normalized interests."""
    interests = await UserRepository.list_all_interests(db)
    return [InterestSchema.model_validate(i) for i in interests]


@router.post(
    "/interests",
    summary="Update User Selected Interests",
    description="Links user's selected interest slugs to their profile in user_interests table. Requires X-Telegram-Init-Data header.",
)
async def update_user_interests(
    req: InterestSelectionRequest,
    tg_user: dict = Depends(require_telegram_user),
    db: AsyncSession = Depends(get_db)
):
    """Updates user's selected interests in normalized junction table."""
    # Use the verified telegram_id from initData, not from request body
    verified_tg_id = int(tg_user["id"])
    matching_interests = await UserRepository.update_user_interests(db, verified_tg_id, req.interest_slugs)
    if matching_interests is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found. Please start @paza_events_bot on Telegram first."
        )

    return {
        "message": f"Successfully updated {len(matching_interests)} interests for user.",
        "telegram_id": verified_tg_id,
        "selected_slugs": [i.slug for i in matching_interests]
    }


class UserSearchResult(BaseModel):
    telegram_id: int
    full_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None


@router.get(
    "/search",
    response_model=List[UserSearchResult],
    summary="Search Registered Users by Username or Name",
    description="Debounced search endpoint for finding users to invite. Requires X-Telegram-Init-Data header.",
)
async def search_users(
    query: str = Query(..., min_length=1, description="Username or full name query"),
    tg_user: dict = Depends(require_telegram_user),
    db: AsyncSession = Depends(get_db)
):
    clean_q = query.strip().lstrip("@").lower()
    if not clean_q:
        return []

    try:
        from app.db.models import User
        from sqlalchemy import select, or_, and_, func

        stmt = (
            select(User)
            .where(
                # Only match users that have a non-empty username or full_name
                or_(
                    and_(
                        User.username.isnot(None),
                        func.length(User.username) > 0,
                        User.username.ilike(f"%{clean_q}%"),
                    ),
                    and_(
                        User.full_name.isnot(None),
                        func.length(User.full_name) > 0,
                        User.full_name.ilike(f"%{clean_q}%"),
                    ),
                )
            )
            .limit(10)
        )
        res = await db.execute(stmt)
        users = res.scalars().all()
        return [
            UserSearchResult(
                telegram_id=u.telegram_id,
                full_name=u.full_name or u.username or "User",
                username=u.username if u.username else None,
                photo_url=None,
            )
            for u in users
        ]
    except Exception as e:
        logger.error(f"Error searching users: {e}")
        return []
