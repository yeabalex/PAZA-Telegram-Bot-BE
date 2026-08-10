"""Pydantic schemas for Organizer authentication, session, and profile management."""

import json
import uuid
from datetime import datetime
from typing import Optional, List, Any, Union
from pydantic import BaseModel, Field, model_validator


# --------------------------------------------------------------------------------
# Auth Request & Response Schemas
# --------------------------------------------------------------------------------
class OrganizerEmailAuthRequest(BaseModel):
    email: str = Field(..., description="Organizer email address")
    password: str = Field(..., min_length=6, description="Account password")
    full_name: Optional[str] = Field(None, description="Organizer contact full name")


class OrganizerGoogleAuthRequest(BaseModel):
    id_token: Optional[str] = Field(None, description="Google OAuth ID Token credential")
    google_id: Optional[str] = Field(None, description="Google OAuth Subject ID (dev mode)")
    email: Optional[str] = Field(None, description="Google Account email (dev mode)")
    full_name: Optional[str] = Field(None, description="Google Account display name (dev mode)")


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: uuid.UUID
    email: str
    is_registered_organizer: bool


# --------------------------------------------------------------------------------
# Organizer Profile Schemas
# --------------------------------------------------------------------------------
import json

class OrganizerProfileCreateUpdate(BaseModel):
    org_name: str = Field(..., min_length=2, max_length=255, description="Name of the Organization / Host")
    username: Optional[str] = Field(None, min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9_.-]+$", description="Unique organizer handle/username")
    category: Optional[str] = Field(None, max_length=100, description="Event Category (e.g., Music, Tech, Nightlife)")
    logo_url: Optional[str] = Field(None, max_length=500, description="URL of organizer logo")
    bio: Optional[str] = Field(None, description="Short bio / description of the organizer")
    support_phone: Optional[str] = Field(None, max_length=50, description="Support phone number")
    social_links: Optional[List[Any]] = Field(None, description="List of social media URLs or handles")
    payout_bank_details: Optional[str] = Field(None, description="Bank payout details string or JSON")
    telebirr_phone: Optional[str] = Field(None, description="Telebirr phone number")
    telebirr_name: Optional[str] = Field(None, description="Telebirr account holder name")
    cbe_account: Optional[str] = Field(None, description="CBE account number")
    cbe_name: Optional[str] = Field(None, description="CBE account holder name")


class OrganizerProfileResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    org_name: str
    username: Optional[str] = None
    category: Optional[str] = None
    logo_url: Optional[str] = None
    bio: Optional[str] = None
    support_phone: Optional[str] = None
    social_links: Optional[List[Any]] = None
    payout_bank_details: Optional[str] = None
    telebirr_phone: Optional[str] = None
    telebirr_name: Optional[str] = None
    cbe_account: Optional[str] = None
    cbe_name: Optional[str] = None
    is_verified: bool = False
    subscriber_count: int = 0
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def populate_bank_fields(cls, data: Any) -> Any:
        """Parse JSON payout_bank_details if available to extract telebirr and cbe fields."""
        payout_raw = getattr(data, "payout_bank_details", None) if not isinstance(data, dict) else data.get("payout_bank_details")
        if payout_raw and isinstance(payout_raw, str):
            try:
                parsed = json.loads(payout_raw)
                if isinstance(parsed, dict):
                    if isinstance(data, dict):
                        data["telebirr_phone"] = parsed.get("telebirr_phone")
                        data["telebirr_name"] = parsed.get("telebirr_name")
                        data["cbe_account"] = parsed.get("cbe_account")
                        data["cbe_name"] = parsed.get("cbe_name")
                    else:
                        setattr(data, "telebirr_phone", parsed.get("telebirr_phone"))
                        setattr(data, "telebirr_name", parsed.get("telebirr_name"))
                        setattr(data, "cbe_account", parsed.get("cbe_account"))
                        setattr(data, "cbe_name", parsed.get("cbe_name"))
            except Exception:
                pass
        return data

    class Config:
        from_attributes = True


class UsernameCheckResponse(BaseModel):
    available: bool
    reason: Optional[str] = None
    username: str


class OrganizerSessionResponse(BaseModel):
    authenticated: bool
    user_id: Optional[uuid.UUID] = None
    email: Optional[str] = None
    role: Optional[str] = None
    is_registered_organizer: bool = False
    organizer: Optional[OrganizerProfileResponse] = None


# --------------------------------------------------------------------------------
# Organizer Event Management Schemas
# --------------------------------------------------------------------------------
class OrganizerEventCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=255, description="Title of the event")
    short_description: Optional[str] = Field(None, max_length=500, description="Short summary / tagline")
    description: Optional[str] = Field(None, description="Detailed description of event")
    start_time: datetime = Field(..., description="Start date and time of the event")
    end_time: Optional[datetime] = Field(None, description="End date and time of the event")
    venue_name: Optional[str] = Field(None, max_length=255, description="Name of the venue")
    sub_city: Optional[str] = Field(None, max_length=100, description="Location e.g. Bole, Kirkos, Kazanchis")
    location_gps: Optional[str] = Field(None, max_length=255, description="GPS coordinates or maps link")
    price_etb: float = Field(0.0, ge=0.0, description="Entrance ticket price in ETB (0 for free)")
    image_url: Optional[str] = Field(None, max_length=500, description="Event poster image URL")
    category_slug: Optional[str] = Field(None, max_length=100, description="Category slug e.g., music, tech, art")


class OrganizerEventUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=2, max_length=255)
    short_description: Optional[str] = None
    description: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    venue_name: Optional[str] = None
    sub_city: Optional[str] = None
    location_gps: Optional[str] = None
    price_etb: Optional[float] = Field(None, ge=0.0)
    image_url: Optional[str] = None
    category_slug: Optional[str] = None


class OrganizerEventResponse(BaseModel):
    id: uuid.UUID
    organizer_id: Optional[uuid.UUID] = None
    interest_id: Optional[uuid.UUID] = None
    title: str
    short_description: Optional[str] = None
    description: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    venue_name: Optional[str] = None
    location_gps: Optional[str] = None
    sub_city: Optional[str] = None
    price_etb: float = 0.0
    image_url: Optional[str] = None
    rsvp_count: int = 0
    category_slug: Optional[str] = None
    is_organizer_verified: bool = False
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def populate_category_slug(cls, data: Any) -> Any:
        if hasattr(data, "interest") and data.interest and hasattr(data.interest, "slug"):
            setattr(data, "category_slug", data.interest.slug)
        return data

    @model_validator(mode="before")
    @classmethod
    def populate_verified(cls, data: Any) -> Any:
        """Pull is_verified from the parent organizer relationship if available."""
        if hasattr(data, "organizer") and data.organizer and hasattr(data.organizer, "is_verified"):
            setattr(data, "is_organizer_verified", data.organizer.is_verified)
        return data

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Organizer RSVP View Schema
# ---------------------------------------------------------------------------
class OrganizerRsvpUserSchema(BaseModel):
    """RSVP attendee info surfaced to the organizer dashboard."""
    telegram_id: int
    first_name: str
    full_name: Optional[str] = None
    username: Optional[str] = None
    photo_url: Optional[str] = None
    message: Optional[str] = None
    transaction_id: Optional[str] = None
    screenshot_url: Optional[str] = None
    payment_method: Optional[str] = None
    ticket_code: Optional[str] = None
    status: Optional[str] = "pending"
    created_at: Optional[Union[str, datetime]] = None

    class Config:
        from_attributes = True

