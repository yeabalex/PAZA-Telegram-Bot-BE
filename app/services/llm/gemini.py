"""Google Gemini LLM Extraction Provider."""

import json
import logging
import httpx
from app.core.config import settings
from app.schemas.event import EventExtractionResult
from app.services.llm.base import BaseLLMProvider, EXTRACTION_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class GeminiLLMProvider(BaseLLMProvider):
    """Gemini API Provider for Event Extraction."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.GEMINI_API_KEY

    @property
    def name(self) -> str:
        return "Gemini"

    async def extract_event(self, text: str) -> EventExtractionResult:
        if not self.api_key:
            raise ValueError("No GEMINI_API_KEY provided.")

        models_to_try = ["gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-2.0-flash-lite", "gemini-2.5-flash"]
        last_error = None
        for model_id in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={self.api_key}"
            payload = {
                "contents": [
                    {
                        "parts": [
                            {"text": f"{EXTRACTION_SYSTEM_PROMPT}\n\nRaw Post Text:\n{text}"}
                        ]
                    }
                ],
                "generationConfig": {
                    "response_mime_type": "application/json"
                }
            }

            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    res_json = response.json()
                    candidate_text = res_json["candidates"][0]["content"]["parts"][0]["text"]
                    parsed = json.loads(candidate_text)
                    return EventExtractionResult(**parsed)
                elif response.status_code == 429:
                    logger.info(f"Gemini LLM model [{model_id}] hit 429 rate limit. Trying next model endpoint...")
                    last_error = f"Gemini API HTTP Error 429: {response.text}"
                else:
                    last_error = f"Gemini API HTTP Error {response.status_code}: {response.text}"

        raise RuntimeError(last_error or "Gemini API request failed across all model endpoints.")


    def _heuristic_fallback(self, text: str) -> EventExtractionResult:
        """Resilient fallback parser when API key is missing or endpoint is offline."""
        from app.services.scraper.pre_filter import passes_pre_filter
        is_evt = passes_pre_filter(text)
        if not is_evt:
            return EventExtractionResult(is_event=False, confidence_score=0.9)

        return EventExtractionResult(
            is_event=True,
            title="[Gemini Extracted Event] " + text[:40] + "...",
            description=text,
            short_summary=text[:120],
            start_datetime="Upcoming",
            end_datetime=None,
            venue_name="Addis Ababa Venue",
            location_gps=None,
            sub_city="Bole",
            entrance_fee_etb=200.0,
            image_url=None,
            category="General",
            confidence_score=0.8
        )

