"""SQLAlchemy ORM Database Models based on ERD Diagram."""

import uuid
from datetime import datetime, timezone
from typing import Optional, List
from sqlalchemy import (
    String, BigInteger, Text, Boolean, Integer, Numeric,
    DateTime, ForeignKey, UniqueConstraint, Index, JSON, Enum as SQLEnum
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import enum


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM models."""
    pass


class UserRole(str, enum.Enum):
    USER = "USER"
    ORGANIZER = "ORGANIZER"
    ADMIN = "ADMIN"


class TransactionStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class TicketStatus(str, enum.Enum):
    VALID = "VALID"
    USED = "USED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------------
# 1. USERS MODEL
# --------------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, unique=True, nullable=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True, index=True)
    hashed_password: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    google_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone_number: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    preferred_language: Mapped[str] = mapped_column(String(10), default="en")
    role: Mapped[UserRole] = mapped_column(SQLEnum(UserRole), default=UserRole.USER, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    organizer_profile: Mapped[Optional["Organizer"]] = relationship("Organizer", back_populates="user", uselist=False, cascade="all, delete-orphan")
    interests: Mapped[List["UserInterest"]] = relationship("UserInterest", back_populates="user", cascade="all, delete-orphan")
    tickets: Mapped[List["Ticket"]] = relationship("Ticket", back_populates="user", cascade="all, delete-orphan")
    transactions: Mapped[List["Transaction"]] = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")
    bookmarks: Mapped[List["Bookmark"]] = relationship("Bookmark", back_populates="user", cascade="all, delete-orphan")
    subscriptions: Mapped[List["OrganizerSubscriber"]] = relationship("OrganizerSubscriber", back_populates="user", cascade="all, delete-orphan")
    hangouts: Mapped[List["Hangout"]] = relationship("Hangout", back_populates="creator", cascade="all, delete-orphan")
    comments: Mapped[List["Comment"]] = relationship("Comment", back_populates="user", cascade="all, delete-orphan")
    upvotes: Mapped[List["CommentUpvote"]] = relationship("CommentUpvote", back_populates="user", cascade="all, delete-orphan")


# --------------------------------------------------------------------------------
# 2. ORGANIZERS MODEL
# --------------------------------------------------------------------------------
class Organizer(Base):
    __tablename__ = "organizers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    org_name: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(100), unique=True, nullable=True, index=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    logo_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    bio: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    support_phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    social_links: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)
    payout_bank_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    subscriber_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="organizer_profile")
    events: Mapped[List["Event"]] = relationship("Event", back_populates="organizer")
    subscribers: Mapped[List["OrganizerSubscriber"]] = relationship("OrganizerSubscriber", back_populates="organizer", cascade="all, delete-orphan")


# --------------------------------------------------------------------------------
# 3. INTERESTS MODEL
# --------------------------------------------------------------------------------
class Interest(Base):
    __tablename__ = "interests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name_en: Mapped[str] = mapped_column(String(255), nullable=False)
    name_am: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    icon_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    # Relationships
    user_interests: Mapped[List["UserInterest"]] = relationship("UserInterest", back_populates="interest", cascade="all, delete-orphan")
    events: Mapped[List["Event"]] = relationship("Event", back_populates="interest")


# --------------------------------------------------------------------------------
# 4. USER_INTERESTS MODEL
# --------------------------------------------------------------------------------
class UserInterest(Base):
    __tablename__ = "user_interests"
    __table_args__ = (UniqueConstraint("user_id", "interest_id", name="uq_user_interest"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    interest_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("interests.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="interests")
    interest: Mapped["Interest"] = relationship("Interest", back_populates="user_interests")


# --------------------------------------------------------------------------------
# 5. EVENTS MODEL
# --------------------------------------------------------------------------------
class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        Index("idx_events_start_time", "start_time"),
        Index("idx_events_sub_city", "sub_city"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    organizer_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("organizers.id", ondelete="SET NULL"), nullable=True)
    interest_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("interests.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    short_description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    venue_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    location_gps: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sub_city: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    price_etb: Mapped[float] = mapped_column(Numeric(10, 2), default=0.0, nullable=False)
    image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    rsvp_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    organizer: Mapped[Optional["Organizer"]] = relationship("Organizer", back_populates="events")
    interest: Mapped[Optional["Interest"]] = relationship("Interest", back_populates="events")
    tickets: Mapped[List["Ticket"]] = relationship("Ticket", back_populates="event", cascade="all, delete-orphan")
    transactions: Mapped[List["Transaction"]] = relationship("Transaction", back_populates="event", cascade="all, delete-orphan")
    bookmarks: Mapped[List["Bookmark"]] = relationship("Bookmark", back_populates="event", cascade="all, delete-orphan")
    comments: Mapped[List["Comment"]] = relationship("Comment", back_populates="event", cascade="all, delete-orphan")


# --------------------------------------------------------------------------------
# 6. TRANSACTIONS MODEL
# --------------------------------------------------------------------------------
class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (Index("idx_transactions_tx_ref", "tx_ref"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    tx_ref: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    chapa_pay_tx_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    amount_etb: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    status: Mapped[TransactionStatus] = mapped_column(SQLEnum(TransactionStatus), default=TransactionStatus.PENDING, nullable=False)
    raw_webhook_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="transactions")
    event: Mapped["Event"] = relationship("Event", back_populates="transactions")
    ticket: Mapped[Optional["Ticket"]] = relationship("Ticket", back_populates="transaction", uselist=False)


# --------------------------------------------------------------------------------
# 7. TICKETS MODEL
# --------------------------------------------------------------------------------
class Ticket(Base):
    __tablename__ = "tickets"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    transaction_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), ForeignKey("transactions.id", ondelete="SET NULL"), unique=True, nullable=True)
    qr_code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[TicketStatus] = mapped_column(SQLEnum(TicketStatus), default=TicketStatus.VALID, nullable=False)
    checked_in_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="tickets")
    user: Mapped["User"] = relationship("User", back_populates="tickets")
    transaction: Mapped[Optional["Transaction"]] = relationship("Transaction", back_populates="ticket")


# --------------------------------------------------------------------------------
# 8. BOOKMARKS MODEL
# --------------------------------------------------------------------------------
class Bookmark(Base):
    __tablename__ = "bookmarks"
    __table_args__ = (UniqueConstraint("user_id", "event_id", name="uq_user_bookmark"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="bookmarks")
    event: Mapped["Event"] = relationship("Event", back_populates="bookmarks")


# --------------------------------------------------------------------------------
# 9. ORGANIZER_SUBSCRIBERS MODEL
# --------------------------------------------------------------------------------
class OrganizerSubscriber(Base):
    __tablename__ = "organizer_subscribers"
    __table_args__ = (UniqueConstraint("user_id", "organizer_id", name="uq_organizer_subscriber"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    organizer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("organizers.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="subscriptions")
    organizer: Mapped["Organizer"] = relationship("Organizer", back_populates="subscribers")


# --------------------------------------------------------------------------------
# 10. HANGOUTS MODEL
# --------------------------------------------------------------------------------
class Hangout(Base):
    __tablename__ = "hangouts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    creator_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    header: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    creator: Mapped["User"] = relationship("User", back_populates="hangouts")


# --------------------------------------------------------------------------------
# 11. COMMENTS MODEL
# --------------------------------------------------------------------------------
class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("events.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    upvote_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    event: Mapped["Event"] = relationship("Event", back_populates="comments")
    user: Mapped["User"] = relationship("User", back_populates="comments")
    upvotes: Mapped[List["CommentUpvote"]] = relationship("CommentUpvote", back_populates="comment", cascade="all, delete-orphan")


# --------------------------------------------------------------------------------
# 12. COMMENT_UPVOTES MODEL
# --------------------------------------------------------------------------------
class CommentUpvote(Base):
    __tablename__ = "comment_upvotes"
    __table_args__ = (UniqueConstraint("user_id", "comment_id", name="uq_comment_upvote"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    comment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("comments.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="upvotes")
    comment: Mapped["Comment"] = relationship("Comment", back_populates="upvotes")


# --------------------------------------------------------------------------------
# 13. SCRAPER_TARGETS MODEL
# --------------------------------------------------------------------------------
class ScraperTargetType(str, enum.Enum):
    USERNAME = "username"
    HASHTAG = "hashtag"
    KEYWORD = "keyword"


class ScraperPlatformEnum(str, enum.Enum):
    TELEGRAM = "telegram"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    WEB = "web"


class ScraperTargetDB(Base):
    __tablename__ = "scraper_targets"
    __table_args__ = (
        UniqueConstraint("platform", "target_type", "value", name="uq_scraper_target"),
        Index("idx_scraper_targets_platform", "platform"),
        Index("idx_scraper_targets_active", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform: Mapped[ScraperPlatformEnum] = mapped_column(
        SQLEnum(ScraperPlatformEnum), nullable=False
    )
    target_type: Mapped[ScraperTargetType] = mapped_column(
        SQLEnum(ScraperTargetType), nullable=False
    )
    value: Mapped[str] = mapped_column(
        String(255), nullable=False,
        comment="Channel name, hashtag, or keyword to scrape"
    )
    last_watermark: Mapped[str] = mapped_column(
        String(255), default="0", nullable=False,
        comment="Last processed ID — message_id for TG, shortcode for IG, video_id for TT"
    )
    max_posts_per_cycle: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )


# --------------------------------------------------------------------------------
# 14. SAVED_SCRAPED_EVENTS MODEL
# --------------------------------------------------------------------------------
class SavedScrapedEvent(Base):
    __tablename__ = "saved_scraped_events"
    __table_args__ = (
        UniqueConstraint("telegram_id", "event_id", name="uq_saved_scraped_event_user"),
        Index("idx_saved_scraped_events_tg_id", "telegram_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )


# --------------------------------------------------------------------------------
# 15. EVENT RSVP MODEL — Tracks users "going" to an event with TG profile cache
# --------------------------------------------------------------------------------
class EventRsvp(Base):
    __tablename__ = "event_rsvps"
    __table_args__ = (
        UniqueConstraint("telegram_id", "event_id", name="uq_rsvp_user_event"),
        Index("idx_rsvp_event_id", "event_id"),
        Index("idx_rsvp_telegram_id", "telegram_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    telegram_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    first_name: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    photo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message: Mapped[Optional[str]] = mapped_column(String(140), nullable=True)
    transaction_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    screenshot_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    payment_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    ticket_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="pending", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
