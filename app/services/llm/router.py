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

    async def extract_event_alternating(self, text: str) -> Tuple[EventExtractionResult, str]:
        """Extract event details using alternating LLM providers with valid API keys.
        
        Returns tuple of (EventExtractionResult, provider_name).
        Falls back to next configured provider if primary choice fails.
        """
        active_providers = self._get_active_providers()
        attempts = 0
        total_attempts = len(active_providers)

        while attempts < total_attempts:
            provider = self._get_next_provider()
            try:
                logger.info(f"Extracting event using provider: [{provider.name}]")
                result = await provider.extract_event(text)
                return result, provider.name
            except Exception as e:
                logger.warning(f"Provider [{provider.name}] skipped/failed ({e}). Moving to next API key...")
                attempts += 1

        # Ultimate fallback only if NO API keys work
        logger.error("All configured LLM provider API keys failed. Using fallback parser.")
        fallback = GeminiLLMProvider()._heuristic_fallback(text)
        return fallback, "Fallback"

