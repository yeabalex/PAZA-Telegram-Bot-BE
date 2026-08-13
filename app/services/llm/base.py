"""Base LLM Provider Abstract Interface with Date Context & ISO Schema."""

import abc
from datetime import datetime, timezone
from typing import List
from app.schemas.event import EventExtractionResult, MultiEventExtractionResult


def get_extraction_prompt(current_dt: datetime = None) -> str:
    """Generates the extraction prompt with current date context to filter past events."""
    now = current_dt or datetime.now(timezone.utc)
    current_date_str = now.strftime("%Y-%m-%d %H:%M:%S UTC")

    return f"""You are an expert AI event extractor for Addis Ababa, Ethiopia.
Current Reference Time: {current_date_str}.

Your task is to analyze raw social media / Telegram post text and determine if it announces one or more UPCOMING or ONGOING events.

STRICT RULES:
1. Past Event Filtering: Check if the event date in the text has already passed relative to Current Reference Time ({current_date_str}). If the event has ALREADY PASSED, ignore it or set is_event=False.
2. Detection: Set is_event=True ONLY if it represents a genuine upcoming/ongoing event (concert, festival, workshop, conference, party, exhibition, bazaar, sports, open mic, etc.). Set is_event=False for past events, general news, hiring posts, or chat.
3. Standardized ISO 8601 Datetimes: Format start_datetime and end_datetime strictly as ISO 8601 strings (YYYY-MM-DDTHH:MM:SS). Assume year {now.year} if year is omitted. If end_datetime is not mentioned in text, set end_datetime to 23:59:59 on the event date.
4. MULTIPLE EVENTS PER POST: If a single post announces MULTIPLE distinct events (e.g. separate concerts on different dates/venues, or a multi-event lineup), extract EACH event separately into the "events" array. Do NOT combine separate events into a single entry.
5. CLEAN & HIGH-QUALITY TITLES: Extract a clear, specific, professional event title. NEVER output generic, meaningless, or senseless titles such as "Events in Addis Ababa", "Check this out", "Promo", "Announcement", "Test", or raw social handles. If a specific title is missing, construct a clear descriptive title based on the event activity (e.g. "Live Jazz & Wine Night").
6. RICH & ENGAGING DESCRIPTION: Provide a rich, polished, and comprehensive `description` detailing what attendees can expect, key activities, special performers/guests, schedule, and entry instructions. Filter out spam, raw links, phone numbers, and repetitive hashtags into clean, engaging sentences.
7. CRISP SHORT SUMMARY: `short_summary` must be a captivating 1-2 sentence executive snapshot summarizing the event experience.

Return ONLY valid JSON matching this schema:
{{
  "is_event": boolean,
  "events": [
    {{
      "is_event": true,
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
  ]
}}
"""

# Default prompt for backwards compatibility
EXTRACTION_SYSTEM_PROMPT = get_extraction_prompt()


def parse_llm_json_events(parsed: dict) -> List[EventExtractionResult]:
    """Parse raw LLM JSON response dict into a list of EventExtractionResult objects."""
    results: List[EventExtractionResult] = []

    # 1. Multi-event list format
    if "events" in parsed and isinstance(parsed["events"], list):
        for item in parsed["events"]:
            if isinstance(item, dict):
                if "is_event" not in item:
                    item["is_event"] = True
                try:
                    evt = EventExtractionResult(**item)
                    if evt.is_event:
                        results.append(evt)
                except Exception:
                    pass
        return results

    # 2. Single event object format
    if "is_event" in parsed:
        try:
            evt = EventExtractionResult(**parsed)
            if evt.is_event:
                results.append(evt)
        except Exception:
            pass
        return results

    return []


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

    async def extract_events(self, text: str) -> List[EventExtractionResult]:
        """Extract multiple events from raw post text if present."""
        res = await self.extract_event(text)
        return [res] if res and res.is_event else []
