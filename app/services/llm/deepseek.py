"""DeepSeek LLM Extraction Provider."""

import json
import logging
import httpx
from app.core.config import settings
from app.schemas.event import EventExtractionResult
from app.services.llm.base import BaseLLMProvider, get_extraction_prompt

logger = logging.getLogger(__name__)


class DeepSeekLLMProvider(BaseLLMProvider):
    """DeepSeek API Provider for Event Extraction (OpenAI Compatible API)."""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or settings.DEEPSEEK_API_KEY

    @property
    def name(self) -> str:
        return "DeepSeek"

    async def extract_event(self, text: str) -> EventExtractionResult:
        if not self.api_key:
            raise ValueError("No DEEPSEEK_API_KEY provided.")

        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": get_extraction_prompt()},
                {"role": "user", "content": f"Raw Post Text:\n{text}"}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }


        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                raise RuntimeError(f"DeepSeek API HTTP Error {response.status_code}: {response.text}")

            res_json = response.json()
            content = res_json["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            return EventExtractionResult(**parsed)


    def _heuristic_fallback(self, text: str) -> EventExtractionResult:
        from app.services.scraper.pre_filter import passes_pre_filter
        is_evt = passes_pre_filter(text)
        if not is_evt:
            return EventExtractionResult(is_event=False, confidence_score=0.9)

        return EventExtractionResult(
            is_event=True,
            title="[DeepSeek Extracted Event] " + text[:40] + "...",
            description=text,
            short_summary=text[:120],
            start_datetime="Upcoming",
            end_datetime=None,
            venue_name="Addis Ababa Venue",
            location_gps=None,
            sub_city="Kazanchis",
            entrance_fee_etb=300.0,
            image_url=None,
            category="Tech",
            confidence_score=0.85
        )

