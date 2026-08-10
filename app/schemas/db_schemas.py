"""Pydantic schemas corresponding to database tables in ERD."""

import uuid
from datetime import datetime
from typing import Optional, Any, List
from pydantic import BaseModel, ConfigDict, Field
from app.db.models import UserRole, TransactionStatus, TicketStatus


# 1. USER SCHEMAS
class UserBase(BaseModel):
    telegram_id: int
    full_name: Optional[str] = None
    username: Optional[str] = None
    phone_number: Optional[str] = None
    preferred_language: str = "en"
    role: UserRole = UserRole.USER


class UserCreate(UserBase):
    pass


class UserResponse(UserBase):
    id: uuid.UUID
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# 2. ORGANIZER SCHEMAS
class OrganizerBase(BaseModel):
    org_name: str
    category: Optional[str] = None
    logo_url: Optional[str] = None
    bio: Optional[str] = None
    support_phone: Optional[str] = None
    social_links: Optional[List[Any]] = None
    payout_bank_details: Optional[str] = None


class OrganizerCreate(OrganizerBase):
    user_id: uuid.UUID


class OrganizerResponse(OrganizerBase):
    id: uuid.UUID
    user_id: uuid.UUID
    is_verified: bool
    subscriber_count: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# 3. INTEREST SCHEMAS
class InterestBase(BaseModel):
    slug: str
    name_en: str
    name_am: Optional[str] = None
    icon_name: Optional[str] = None


class InterestCreate(InterestBase):
    pass


class InterestResponse(InterestBase):
    id: uuid.UUID
    model_config = ConfigDict(from_attributes=True)


# 4. EVENT SCHEMAS
class EventBase(BaseModel):
    title: str
    description: Optional[str] = None
    start_time: datetime
    end_time: Optional[datetime] = None
    venue_name: Optional[str] = None
    location_gps: Optional[str] = None
    sub_city: Optional[str] = None
    price_etb: float = 0.0
    image_url: Optional[str] = None


class EventCreate(EventBase):
    organizer_id: Optional[uuid.UUID] = None
    interest_id: Optional[uuid.UUID] = None


class EventResponse(EventBase):
    id: uuid.UUID
    organizer_id: Optional[uuid.UUID] = None
    interest_id: Optional[uuid.UUID] = None
    rsvp_count: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# 5. TRANSACTION SCHEMAS
class TransactionBase(BaseModel):
    amount_etb: float
    payment_method: Optional[str] = None


class TransactionCreate(TransactionBase):
    user_id: uuid.UUID
    event_id: uuid.UUID
    tx_ref: str


class TransactionResponse(TransactionBase):
    id: uuid.UUID
    user_id: uuid.UUID
    event_id: uuid.UUID
    tx_ref: str
    chapa_pay_tx_id: Optional[str] = None
    status: TransactionStatus
    raw_webhook_payload: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


# 6. TICKET SCHEMAS
class TicketBase(BaseModel):
    qr_code_hash: str
    status: TicketStatus = TicketStatus.VALID


class TicketCreate(TicketBase):
    event_id: uuid.UUID
    user_id: uuid.UUID
    transaction_id: Optional[uuid.UUID] = None


class TicketResponse(TicketBase):
    id: uuid.UUID
    event_id: uuid.UUID
    user_id: uuid.UUID
    transaction_id: Optional[uuid.UUID] = None
    checked_in_at: Optional[datetime] = None
    issued_at: datetime
    model_config = ConfigDict(from_attributes=True)


# 7. BOOKMARK SCHEMAS
class BookmarkCreate(BaseModel):
    user_id: uuid.UUID
    event_id: uuid.UUID


class BookmarkResponse(BookmarkCreate):
    id: uuid.UUID
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# 8. ORGANIZER SUBSCRIBER SCHEMAS
class OrganizerSubscriberCreate(BaseModel):
    user_id: uuid.UUID
    organizer_id: uuid.UUID


class OrganizerSubscriberResponse(OrganizerSubscriberCreate):
    id: uuid.UUID
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# 9. HANGOUT SCHEMAS
class HangoutCreate(BaseModel):
    creator_id: uuid.UUID
    header: str
    description: Optional[str] = None


class HangoutResponse(HangoutCreate):
    id: uuid.UUID
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# 10. COMMENT SCHEMAS
class CommentCreate(BaseModel):
    event_id: uuid.UUID
    user_id: uuid.UUID
    content: str


class CommentResponse(CommentCreate):
    id: uuid.UUID
    upvote_count: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


# 11. COMMENT UPVOTE SCHEMAS
class CommentUpvoteCreate(BaseModel):
    user_id: uuid.UUID
    comment_id: uuid.UUID


class CommentUpvoteResponse(CommentUpvoteCreate):
    id: uuid.UUID
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
