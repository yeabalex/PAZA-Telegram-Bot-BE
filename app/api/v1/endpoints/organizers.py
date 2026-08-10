"""Organizer Authentication, Profile Onboarding, and Management Endpoints."""

import json
import logging
import re
import uuid
from typing import Optional, List
from fastapi import APIRouter, Depends, File, Header, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, decode_access_token
from app.db.session import get_db
from app.db.models import Interest
from app.schemas.organizer import (
    OrganizerEmailAuthRequest,
    OrganizerEventCreate,
    OrganizerEventResponse,
    OrganizerEventUpdate,
    OrganizerGoogleAuthRequest,
    OrganizerProfileCreateUpdate,
    OrganizerProfileResponse,
    OrganizerRsvpUserSchema,
    OrganizerSessionResponse,
    TokenResponse,
    UsernameCheckResponse,
)
from app.services.organizer.organizer_repository import OrganizerRepository
from app.services.event.event_repository import EventRepository
from app.services.storage import r2_storage_service

import httpx

from pydantic import BaseModel
from app.services.cache.redis_event_storage import RedisEventStorage

logger = logging.getLogger(__name__)
router = APIRouter()
redis_event_storage = RedisEventStorage()


async def verify_google_id_token(id_token: str) -> Optional[dict]:
    """Verify Google OAuth ID Token via Google's tokeninfo API endpoint."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://oauth2.googleapis.com/tokeninfo",
                params={"id_token": id_token}
            )
            if resp.status_code == 200:
                data = resp.json()
                if "sub" in data and "email" in data:
                    return data
    except Exception as e:
        logger.error(f"Google ID token verification failed: {e}")
    return None


async def get_current_user_id_from_token(authorization: Optional[str] = Header(None)) -> uuid.UUID:
    """Extracts and verifies JWT token from Authorization header."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid Bearer authorization header."
        )

    token = authorization.split(" ")[1]
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token."
        )

    try:
        return uuid.UUID(payload["sub"])
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed user ID in token."
        )


def _is_organizer_profile_complete(organizer) -> bool:
    """Checks if an organizer profile exists and has required non-empty organization name."""
    return organizer is not None and bool(organizer.org_name and organizer.org_name.strip())


@router.post(
    "/auth/email",
    response_model=TokenResponse,
    summary="Organizer Custom Email Login / Registration",
    description="Authenticates or registers an organizer via custom email and password."
)
async def auth_with_email(
    req: OrganizerEmailAuthRequest,
    db: AsyncSession = Depends(get_db)
):
    """Authenticate or register organizer via custom email."""
    try:
        user = await OrganizerRepository.authenticate_or_register_email(
            db=db,
            email=req.email,
            password=req.password,
            full_name=req.full_name
        )
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )

    organizer = await OrganizerRepository.get_organizer_by_user_id(db, user.id)
    token = create_access_token(user_id=str(user.id), email=user.email, role=user.role.value)

    return TokenResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        is_registered_organizer=_is_organizer_profile_complete(organizer)
    )


@router.post(
    "/auth/google",
    response_model=TokenResponse,
    summary="Organizer Google OAuth Login / Registration",
    description="Authenticates or registers an organizer via Google OAuth token/ID."
)
async def auth_with_google(
    req: OrganizerGoogleAuthRequest,
    db: AsyncSession = Depends(get_db)
):
    """Authenticate or register organizer via Google OAuth."""
    target_google_id = req.google_id
    target_email = req.email
    target_name = req.full_name

    if req.id_token:
        google_info = await verify_google_id_token(req.id_token)
        if not google_info:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid Google OAuth ID token signature."
            )
        target_google_id = google_info.get("sub")
        target_email = google_info.get("email")
        target_name = google_info.get("name") or target_name

    if not target_google_id or not target_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing valid Google credentials or ID token."
        )

    user = await OrganizerRepository.authenticate_or_register_google(
        db=db,
        google_id=target_google_id,
        email=target_email,
        full_name=target_name
    )

    organizer = await OrganizerRepository.get_organizer_by_user_id(db, user.id)
    token = create_access_token(user_id=str(user.id), email=user.email, role=user.role.value)

    return TokenResponse(
        access_token=token,
        user_id=user.id,
        email=user.email,
        is_registered_organizer=_is_organizer_profile_complete(organizer)
    )


@router.get(
    "/me",
    response_model=OrganizerSessionResponse,
    summary="Get Current Organizer Session & Registration Status",
    description="Verifies the current session token and returns the user's registered organizer profile if present."
)
async def get_current_organizer_session(
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Fetch current session status and organizer details."""
    if not authorization or not authorization.startswith("Bearer "):
        return OrganizerSessionResponse(authenticated=False)

    token = authorization.split(" ")[1]
    payload = decode_access_token(token)
    if not payload or "sub" not in payload:
        return OrganizerSessionResponse(authenticated=False)

    try:
        user_id = uuid.UUID(payload["sub"])
    except ValueError:
        return OrganizerSessionResponse(authenticated=False)

    user = await OrganizerRepository.get_user_by_id(db, user_id)
    if not user:
        return OrganizerSessionResponse(authenticated=False)

    organizer = await OrganizerRepository.get_organizer_by_user_id(db, user_id)
    is_complete = _is_organizer_profile_complete(organizer)

    return OrganizerSessionResponse(
        authenticated=True,
        user_id=user.id,
        email=user.email,
        role=user.role.value,
        is_registered_organizer=is_complete,
        organizer=OrganizerProfileResponse.model_validate(organizer) if is_complete else None
    )


@router.post(
    "/profile",
    response_model=OrganizerProfileResponse,
    summary="Create or Update Organizer Profile",
    description="Submits the required organizer schema information and completes organizer registration."
)
async def create_or_update_organizer_profile(
    data: OrganizerProfileCreateUpdate,
    user_id: uuid.UUID = Depends(get_current_user_id_from_token),
    db: AsyncSession = Depends(get_db)
):
    """Save or update organizer schema profile for authenticated user."""
    try:
        organizer = await OrganizerRepository.create_or_update_organizer(
            db=db,
            user_id=user_id,
            data=data
        )
        return OrganizerProfileResponse.model_validate(organizer)
    except ValueError as ve:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(ve)
        )
    except Exception as e:
        logger.error(f"Error saving organizer profile for user_id={user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save organizer profile."
        )


from app.services.storage import cloudinary_storage_service, r2_storage_service


@router.post(
    "/upload-logo",
    summary="Upload Organizer Profile Logo",
    description="Protected endpoint to upload organizer logo picture to Cloudinary / R2 storage."
)
async def upload_organizer_logo(
    file: UploadFile = File(...),
    user_id: uuid.UUID = Depends(get_current_user_id_from_token)
):
    """Protected endpoint to upload organizer logo image."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be an image (JPEG, PNG, WebP, etc.)."
        )

    try:
        if cloudinary_storage_service._is_configured():
            url = await cloudinary_storage_service.upload_file(file=file, folder=f"paza/organizers/{user_id}")
        else:
            url = await r2_storage_service.upload_file(file=file, folder=f"organizers/{user_id}")
        return {"url": url}
    except Exception as e:
        logger.error(f"Error uploading logo image for user_id={user_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload logo image."
        )


USERNAME_REGEX = re.compile(r"^[a-zA-Z0-9_.-]{3,30}$")


@router.get(
    "/check-username",
    response_model=UsernameCheckResponse,
    summary="Check Organizer Username Availability",
    description="Checks if an organizer username/handle is valid and unique."
)
async def check_username_availability(
    username: str,
    authorization: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Checks whether the requested organizer handle is available."""
    clean_username = username.strip().lower()

    if not clean_username:
        return UsernameCheckResponse(available=False, reason="Username cannot be empty.", username=username)

    if len(clean_username) < 3:
        return UsernameCheckResponse(available=False, reason="Username must be at least 3 characters.", username=clean_username)

    if len(clean_username) > 30:
        return UsernameCheckResponse(available=False, reason="Username must be 30 characters or fewer.", username=clean_username)

    if not USERNAME_REGEX.match(clean_username):
        return UsernameCheckResponse(available=False, reason="Only letters, numbers, underscores, dashes & dots allowed.", username=clean_username)

    current_user_id = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        payload = decode_access_token(token)
        if payload and "sub" in payload:
            try:
                current_user_id = uuid.UUID(payload["sub"])
            except ValueError:
                pass

    existing = await OrganizerRepository.get_organizer_by_username(db, clean_username, exclude_user_id=current_user_id)
    if existing:
        return UsernameCheckResponse(available=False, reason=f"Username '@{clean_username}' is already taken.", username=clean_username)

    return UsernameCheckResponse(available=True, reason=None, username=clean_username)


# ════════════════════════════════════════════════════════════════════════════════
# ORGANIZER EVENT MANAGEMENT ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════════

async def get_current_organizer_from_token(
    user_id: uuid.UUID = Depends(get_current_user_id_from_token),
    db: AsyncSession = Depends(get_db)
):
    organizer = await OrganizerRepository.get_organizer_by_user_id(db, user_id)
    if not organizer or not _is_organizer_profile_complete(organizer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Organizer profile setup required before managing events."
        )
    return organizer


@router.get(
    "/events",
    response_model=List[OrganizerEventResponse],
    summary="List Logged-In Organizer's Events",
    description="Fetches all events created by the authenticated organizer."
)
async def list_my_organizer_events(
    organizer = Depends(get_current_organizer_from_token),
    db: AsyncSession = Depends(get_db)
):
    events = await EventRepository.list_organizer_owned_events(db, organizer.id)
    return [OrganizerEventResponse.model_validate(e) for e in events]


def has_bank_details_configured(organizer) -> bool:
    """Check if organizer has configured valid Telebirr or CBE bank details."""
    raw = getattr(organizer, "payout_bank_details", None)
    if not raw or not str(raw).strip():
        return False
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            has_telebirr = bool((parsed.get("telebirr_phone") or "").strip())
            has_cbe = bool((parsed.get("cbe_account") or "").strip())
            return has_telebirr or has_cbe
    except Exception:
        pass
    return len(str(raw).strip()) > 5


@router.post(
    "/events",
    response_model=OrganizerEventResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create New Organizer Event",
    description="Publishes a new event under the authenticated organizer."
)
async def create_organizer_event(
    payload: OrganizerEventCreate,
    organizer = Depends(get_current_organizer_from_token),
    db: AsyncSession = Depends(get_db)
):
    if payload.price_etb > 0 and not has_bank_details_configured(organizer):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must configure your payment details (Telebirr or CBE account) in Profile Settings before publishing paid events."
        )
    try:
        event = await EventRepository.create_organizer_event(db, organizer.id, payload)
        return OrganizerEventResponse.model_validate(event)
    except Exception as e:
        logger.error(f"Error creating event: {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.put(
    "/events/{event_id}",
    response_model=OrganizerEventResponse,
    summary="Update Organizer Event",
    description="Updates an existing event owned by the authenticated organizer."
)
async def update_organizer_event(
    event_id: uuid.UUID,
    payload: OrganizerEventUpdate,
    organizer = Depends(get_current_organizer_from_token),
    db: AsyncSession = Depends(get_db)
):
    if payload.price_etb is not None and payload.price_etb > 0 and not has_bank_details_configured(organizer):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You must configure your payment details (Telebirr or CBE account) in Profile Settings before publishing paid events."
        )
    event = await EventRepository.update_organizer_event(db, event_id, organizer.id, payload)
    if not event:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found or unauthorized.")
    return OrganizerEventResponse.model_validate(event)


@router.delete(
    "/events/{event_id}",
    summary="Delete Organizer Event",
    description="Deletes an event owned by the authenticated organizer."
)
async def delete_organizer_event(
    event_id: uuid.UUID,
    organizer = Depends(get_current_organizer_from_token),
    db: AsyncSession = Depends(get_db)
):
    deleted = await EventRepository.delete_organizer_event(db, event_id, organizer.id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found or unauthorized.")
    return {"status": "success", "message": "Event deleted successfully."}


@router.post(
    "/upload-event-image",
    summary="Upload Event Poster Image",
    description="Uploads event poster image to storage (Cloudinary or R2) and returns the public URL."
)
async def upload_event_image(
    file: UploadFile = File(...),
    organizer = Depends(get_current_organizer_from_token)
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file must be an image (JPEG, PNG, WebP)."
        )

    try:
        if cloudinary_storage_service._is_configured():
            url = await cloudinary_storage_service.upload_file(file=file, folder=f"paza/events/{organizer.id}")
        else:
            url = await r2_storage_service.upload_file(file=file, folder=f"events/{organizer.id}")
        return {"url": url}
    except Exception as e:
        logger.error(f"Error uploading event image: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to upload event image.")


@router.get(
    "/categories",
    summary="List Database Event Categories / Interests",
    description="Returns all normalized categories stored in PostgreSQL interests table."
)
async def list_db_categories(db: AsyncSession = Depends(get_db)):
    stmt = select(Interest).order_by(Interest.name_en.asc())
    res = await db.execute(stmt)
    interests = res.scalars().all()
    return [
        {
            "id": str(i.id),
            "slug": i.slug,
            "name_en": i.name_en,
            "name_am": i.name_am,
            "icon_name": i.icon_name
        }
        for i in interests
    ]


# ---------------------------------------------------------------------------
# Event RSVP List (for organizer dashboard)
# ---------------------------------------------------------------------------
@router.get(
    "/events/{event_id}/rsvps",
    response_model=List[OrganizerRsvpUserSchema],
    summary="List RSVPs for an Organizer's Event",
    description="Returns all RSVP attendees for a specific event owned by the authenticated organizer."
)
async def list_event_rsvps(
    event_id: str,
    organizer = Depends(get_current_organizer_from_token),
    db: AsyncSession = Depends(get_db),
):
    """Fetch RSVP attendee list for an organizer-owned event."""
    return await EventRepository.list_rsvps(db, event_id)


class ConfirmRsvpRequest(BaseModel):
    event_id: str
    telegram_id: int


@router.post(
    "/rsvps/confirm",
    summary="Confirm RSVP Attendance and Send Ticket via Bot",
    description="Marks attendee status as confirmed, generates a ticket pass code, and sends a notification message via Telegram bot."
)
async def confirm_rsvp(
    body: ConfirmRsvpRequest,
    organizer = Depends(get_current_organizer_from_token),
    db: AsyncSession = Depends(get_db),
):
    result = await EventRepository.confirm_rsvp(
        db=db,
        redis_storage=redis_event_storage,
        event_id=body.event_id,
        telegram_id=body.telegram_id,
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="RSVP record not found."
        )
    return result
