"""Base LLM Provider Abstract Interface with Date Context & ISO Schema."""

import abc
from datetime import datetime, timezone
from app.schemas.event import EventExtractionResult


def get_extraction_prompt(current_dt: datetime = None) -> str:
    """Generates the extraction prompt with current date context to filter past events."""
    now = current_dt or datetime.now(timezone.utc)
    current_date_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")

    return f"""You are an expert AI event extractor for Addis Ababa, Ethiopia.
Current Reference Time: {current_date_str}.

Your task is to analyze raw Telegram channel post text and determine if it announces an UPCOMING or ONGOING event.

STRICT RULES:
1. Past Event Filtering: Check if the event date in the text has already passed relative to Current Reference Time ({current_date_str}). If the event has ALREADY PASSED, set is_event=False.
2. Detection: Set is_event=True ONLY if it represents a genuine upcoming/ongoing event (concert, festival, workshop, conference, party, exhibition, bazaar, sports, etc.). Set is_event=False for past events, general news, hiring posts, or chat.
3. Standardized ISO 8601 Datetimes: Format start_datetime and end_datetime strictly as ISO 8601 strings (YYYY-MM-DDTHH:MM:SS). Assume year {now.year} if year is omitted. If end_datetime is not mentioned in text, set end_datetime to 23:59:59 on the event date.

Return ONLY valid JSON matching this schema:
{{
  "is_event": boolean,
  "title": string or null,
  "description": string or null,
  "short_summary": string or null,
  "start_datetime": "YYYY-MM-DDTHH:MM:SS" or null,
  "end_datetime": "YYYY-MM-DDTHH:MM:SS" or null,
  "venue_name": string or null,
  "location_gps": string or null,
  "sub_city": string or null,
  "entrance_fee_etb": float or null,
  "image_url": string or null,
  "category": string or null,
  "confidence_score": float
}}
"""

# Default prompt for backwards compatibility
EXTRACTION_SYSTEM_PROMPT = get_extraction_prompt()


class BaseLLMProvider(abc.ABC):
    """Abstract interface for LLM event extraction providers."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Provider name string."""
        pass

    @abc.abstractmethod
    async def extract_event(self, text: str) -> EventExtractionResult:
        """Extract event details from raw post text."""
        pass
