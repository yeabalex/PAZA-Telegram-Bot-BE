"""User and Interest Pydantic Schemas for Request/Response validation and OpenAPI Docs."""

from typing import List, Optional
from uuid import UUID
from pydantic import BaseModel, Field


class InterestSchema(BaseModel):
    id: UUID = Field(..., description="Unique interest UUID")
    slug: str = Field(..., description="Normalized interest slug (e.g. music, nightlife)")
    name_en: str = Field(..., description="English interest name")
    name_am: Optional[str] = Field(None, description="Amharic interest name")
    icon_name: Optional[str] = Field(None, description="Emoji or icon identifier")

    class Config:
        from_attributes = True


class UserProfileSchema(BaseModel):
    id: UUID = Field(..., description="Unique User UUID")
    telegram_id: int = Field(..., description="Telegram numeric User ID")
    full_name: Optional[str] = Field(None, description="User full name")
    username: Optional[str] = Field(None, description="Telegram @username")
    phone_number: Optional[str] = Field(None, description="Phone number")
    preferred_language: str = Field("en", description="Preferred UI language")
    role: str = Field("USER", description="User role (USER, ORGANIZER, ADMIN)")
    is_registered: bool = Field(..., description="True if phone number is registered")
    interests: List[InterestSchema] = Field(default=[], description="User's selected interests")

    class Config:
        from_attributes = True


class BotStartRequest(BaseModel):
    telegram_id: int = Field(..., description="Telegram numeric User ID")
    full_name: Optional[str] = Field(None, description="Telegram User full name")
    username: Optional[str] = Field(None, description="Telegram username without @")
    preferred_language: str = Field("en", description="Preferred language code")


class PhoneNumberUpdateRequest(BaseModel):
    telegram_id: int = Field(..., description="Telegram numeric User ID")
    phone_number: str = Field(..., description="Phone number shared via Telegram contact button")


class InterestSelectionRequest(BaseModel):
    telegram_id: int = Field(..., description="Telegram numeric User ID")
    interest_slugs: List[str] = Field(..., description="List of selected interest slugs (e.g. ['music', 'food'])")
