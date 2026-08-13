"""LLM Provider Router for Alternating / Round-Robin Execution across Gemini, DeepSeek, and Groq."""

import logging
from typing import List, Tuple
from app.schemas.event import EventExtractionResult
from app.services.llm.base import BaseLLMProvider
from app.services.llm.gemini import GeminiLLMProvider
from app.services.llm.deepseek import DeepSeekLLMProvider
from app.services.llm.groq import GroqLLMProvider

logger = logging.getLogger(__name__)


class LLMRouter:
    """Manages round-robin rotation and fallback between Gemini, DeepSeek, and Groq LLMs."""

    def __init__(self, providers: List[BaseLLMProvider] = None):
        self.providers = providers or [
            GroqLLMProvider(),
            DeepSeekLLMProvider(),
            GeminiLLMProvider()
        ]
        self._current_index = 0

    def _get_active_providers(self) -> List[BaseLLMProvider]:
        """Filter providers to only those with configured API keys."""
        active = [p for p in self.providers if getattr(p, "api_key", None)]
        return active if active else self.providers

    def _get_next_provider(self) -> BaseLLMProvider:
        """Get next active provider in round-robin sequence."""
        active = self._get_active_providers()
        provider = active[self._current_index % len(active)]
        self._current_index += 1
        return provider

    async def extract_events_alternating(self, text: str) -> Tuple[List[EventExtractionResult], str]:
        """Extract all event details from post text using alternating LLM providers.
        
        Returns tuple of (List[EventExtractionResult], provider_name).
        """
        active_providers = self._get_active_providers()
        attempts = 0
        total_attempts = len(active_providers)

        while attempts < total_attempts:
            provider = self._get_next_provider()
            try:
                logger.info(f"Extracting events using provider: [{provider.name}]")
                results = await provider.extract_events(text)
                return results, provider.name
            except Exception as e:
                logger.warning(f"Provider [{provider.name}] skipped/failed ({e}). Moving to next API key...")
                attempts += 1

        # Ultimate fallback only if NO API keys work
        logger.error("All configured LLM provider API keys failed. Using fallback parser.")
        fallback = GeminiLLMProvider()._heuristic_fallback(text)
        return ([fallback] if fallback.is_event else []), "Fallback"

    async def extract_event_alternating(self, text: str) -> Tuple[EventExtractionResult, str]:
        """Backwards compatibility wrapper — extracts primary event from text."""
        evts, provider = await self.extract_events_alternating(text)
        if evts:
            return evts[0], provider
        fallback = GeminiLLMProvider()._heuristic_fallback(text)
        return fallback, provider

