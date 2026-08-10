"""Event extraction schema models."""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------
class ScraperPlatform(str, Enum):
    """Supported scraping platforms."""
    TELEGRAM = "telegram"
    INSTAGRAM = "instagram"
    TIKTOK = "tiktok"
    WEB = "web"


class TargetType(str, Enum):
    """How the scraper should interpret the target value."""
    USERNAME = "username"   # Scrape a specific user/channel profile
    HASHTAG = "hashtag"     # Scrape posts tagged with a hashtag
    KEYWORD = "keyword"     # Search by keyword (future: Google/web)


# ---------------------------------------------------------------------------
# LLM Extraction Result
# ---------------------------------------------------------------------------
class EventExtractionResult(BaseModel):
    """Structured extraction result returned by LLM extraction workers."""

    is_event: bool = Field(
        ...,
        description="True if the post represents a genuine upcoming/ongoing event, False otherwise."
    )
    title: Optional[str] = Field(
        default=None,
        description="Event title or headline."
    )
    description: Optional[str] = Field(
        default=None,
        description="Detailed full description of the event extracted from post text."
    )
    short_summary: Optional[str] = Field(
        default=None,
        description="Concise 1-2 sentence summary of the event details."
    )
    start_datetime: Optional[str] = Field(
        default=None,
        description="Start date and time of the event (ISO format or descriptive string)."
    )
    end_datetime: Optional[str] = Field(
        default=None,
        description="End date and time of the event if specified."
    )
    venue_name: Optional[str] = Field(
        default=None,
        description="Specific location, building, hotel, hall, or venue name."
    )
    location_gps: Optional[str] = Field(
        default=None,
        description="GPS location or coordinates string if mentioned."
    )
    sub_city: Optional[str] = Field(
        default=None,
        description="Sub-city location in Addis Ababa (e.g. Bole, Kirkos, Kazanchis, Piassa, Arada, etc.)."
    )
    entrance_fee_etb: Optional[float] = Field(
        default=None,
        description="Entrance/Ticket price in Ethiopian Birr (ETB). 0.0 if free, None if unknown."
    )
    image_url: Optional[str] = Field(
        default=None,
        description="Image or banner URL if present in post."
    )
    category: Optional[str] = Field(
        default=None,
        description="Primary interest category: Music, Tech, Networking, Art, Exhibition, Party, Conference, Sports, Workshop, General."
    )
    confidence_score: Optional[float] = Field(
        default=1.0,
        description="Extraction confidence score between 0.0 and 1.0."
    )


# ---------------------------------------------------------------------------
# Scraped Message (raw data from any platform)
# ---------------------------------------------------------------------------
class ScrapedMessage(BaseModel):
    """Raw message scraped from Telegram, Instagram, TikTok, or Web."""

    channel_username: str
    message_id: str | int
    text: str
    date: Optional[datetime] = None
    platform: str = "telegram"
    post_url: Optional[str] = None
    image_url: Optional[str] = None
    is_video: bool = False

    @property
    def task_id(self) -> str:
        """Unique staging and task key identifier."""
        return f"{self.platform}:{self.channel_username}:{self.message_id}"


# ---------------------------------------------------------------------------
# Unified Scraper Target (replaces ChannelConfig, InstagramAccountConfig, etc.)
# ---------------------------------------------------------------------------
class ScraperTarget(BaseModel):
    """Unified scraper target config — works for any platform + target type.

    Examples:
        ScraperTarget(platform="telegram",  target_type="username", value="LinkUpAddis")
        ScraperTarget(platform="instagram", target_type="hashtag",  value="addisevents")
        ScraperTarget(platform="tiktok",    target_type="username", value="linkupaddis")
        ScraperTarget(platform="instagram", target_type="keyword",  value="events in addis")
    """

    platform: ScraperPlatform
    target_type: TargetType
    value: str = Field(..., description="Channel name, hashtag, or keyword to scrape")
    last_watermark: str = Field(
        default="0",
        description="Last processed ID — message_id for TG, shortcode for IG, video_id for TT"
    )
    max_posts: int = Field(default=10, description="Max posts to fetch per cycle")
    is_active: bool = Field(default=True, description="Whether this target is currently active")


# ---------------------------------------------------------------------------
# Backwards-compatible aliases (delegate to ScraperTarget internally)
# ---------------------------------------------------------------------------
class ChannelConfig(BaseModel):
    """Monitored Telegram channel config (backwards compat)."""
    channel_username: str
    last_message_id: int = 0
    platform: str = "telegram"


class InstagramAccountConfig(BaseModel):
    """Monitored Instagram profile or hashtag config (backwards compat)."""
    target_handle_or_hashtag: str
    last_post_id: str = "0"
    is_hashtag: bool = False


class TikTokAccountConfig(BaseModel):
    """Monitored TikTok profile or hashtag config (backwards compat)."""
    target_handle_or_hashtag: str
    last_video_id: str = "0"
    is_hashtag: bool = False


# ---------------------------------------------------------------------------
# API Request & Response Schemas
# ---------------------------------------------------------------------------
class EventSummarySchema(BaseModel):
    id: str = Field(..., description="Unique event identifier")
    title: str = Field(..., description="Event title")
    short_description: Optional[str] = Field(None, description="Short punchline / tagline")
    description: Optional[str] = Field(None, description="Event description summary")
    venue_name: Optional[str] = Field("Addis Ababa", description="Venue location name")
    sub_city: Optional[str] = Field(None, description="Sub city")
    start_datetime: Optional[str] = Field(None, description="Start ISO datetime")
    entrance_fee_etb: Optional[float] = Field(0.0, description="Entrance fee in ETB")
    category: Optional[str] = Field("general", description="Event category slug")
    image_url: Optional[str] = Field(None, description="Event image or poster URL")
    rsvp_count: Optional[int] = Field(0, description="RSVP count")
    max_capacity: Optional[int] = Field(100, description="Capacity limit")
    source_type: str = Field("scraped", description="Distinction: 'scraped' vs 'organizer'")
    organizer_name: Optional[str] = Field(None, description="Organizer name")
    organizer_username: Optional[str] = Field(None, description="Organizer @username handle")
    organizer_logo: Optional[str] = Field(None, description="Organizer logo image URL")
    is_organizer_verified: bool = Field(False, description="Whether the organizer is platform-verified")
    organizer_events_count: Optional[int] = Field(0, description="Total events hosted by this organizer")


class EventDetailSchema(BaseModel):
    id: str = Field(..., description="Unique event identifier")
    title: str = Field(..., description="Event title")
    description: Optional[str] = Field(None, description="Detailed description")
    venue_name: Optional[str] = Field("Addis Ababa", description="Venue location name")
    sub_city: Optional[str] = Field(None, description="Sub city")
    start_datetime: Optional[str] = Field(None, description="Start ISO datetime")
    end_datetime: Optional[str] = Field(None, description="End ISO datetime")
    entrance_fee_etb: Optional[float] = Field(0.0, description="Entrance fee in ETB")
    category: Optional[str] = Field("general", description="Event category slug")
    image_url: Optional[str] = Field(None, description="Event image or poster URL")
    location_gps: Optional[str] = Field(None, description="GPS coordinates lat,lon")
    rsvp_count: int = Field(0, description="Real RSVP count from event_rsvps table")
    source_type: str = Field("scraped", description="Distinction: 'scraped' vs 'organizer'")
    organizer_name: Optional[str] = Field(None, description="Organizer name")
    organizer_username: Optional[str] = Field(None, description="Organizer @username handle")
    organizer_logo: Optional[str] = Field(None, description="Organizer logo image URL")
    is_organizer_verified: bool = Field(False, description="Whether the organizer is platform-verified")
    organizer_events_count: Optional[int] = Field(0, description="Total events hosted by this organizer")
    telebirr_phone: Optional[str] = Field(None, description="Organizer Telebirr phone number")
    telebirr_name: Optional[str] = Field(None, description="Organizer Telebirr holder name")
    cbe_account: Optional[str] = Field(None, description="Organizer CBE account number")
    cbe_name: Optional[str] = Field(None, description="Organizer CBE holder name")


# Alias for backward compatibility
EventResponseSchema = EventSummarySchema


class CategoryInfo(BaseModel):
    slug: str
    label: str
    count: int


class RsvpRequest(BaseModel):
    event_id: str = Field(..., description="Event ID to RSVP to")
    telegram_id: int = Field(..., description="Telegram user ID")
    first_name: str = Field(..., description="User's first name from TG profile")
    full_name: Optional[str] = Field(None, description="Attendee's provided full name")
    username: Optional[str] = Field(None, description="TG username")
    photo_url: Optional[str] = Field(None, description="TG small avatar URL")
    message: Optional[str] = Field(None, max_length=140, description="Optional short going message")
    transaction_id: Optional[str] = Field(None, description="Payment transaction reference/ID")
    screenshot_url: Optional[str] = Field(None, description="Uploaded payment receipt screenshot URL")
    payment_method: Optional[str] = Field(None, description="Payment method used (e.g. Telebirr, CBE)")


class RsvpUserSchema(BaseModel):
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
    created_at: Optional[str] = None


class SaveScrapedEventRequest(BaseModel):
    telegram_id: int
    event_id: str
    event_data: dict

