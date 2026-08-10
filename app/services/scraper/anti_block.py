"""Anti-Block Utilities — shared across all platform scrapers.

Provides:
- Rotating User-Agent pool (realistic browser fingerprints)
- Optional human-like delays (disabled by default for authenticated scraping)
- Optional per-platform cooldown tracker
- Exponential backoff retry wrapper for transient failures (429 / 5xx)

Delays are DISABLED by default since we scrape once/24h with credentials.
Set USE_SCRAPER_DELAYS=true in .env to enable them (e.g. anonymous scraping).
"""

import asyncio
import logging
import os
import random
import time
from typing import Callable, Dict

logger = logging.getLogger(__name__)

# Check if delays are explicitly enabled (default: off for authenticated mode)
_DELAYS_ENABLED = os.getenv("USE_SCRAPER_DELAYS", "false").lower() in ("true", "1", "yes")

# ---------------------------------------------------------------------------
# 1. Realistic User-Agent rotation pool (always active, zero cost)
# ---------------------------------------------------------------------------
USER_AGENTS: list[str] = [
    # Chrome on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    # Firefox on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    # Firefox on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:128.0) Gecko/20100101 Firefox/128.0",
    # Safari on macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
    # Chrome on Linux
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    # Edge on Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
]


def get_random_user_agent() -> str:
    """Return a random realistic browser User-Agent string."""
    return random.choice(USER_AGENTS)


def get_random_headers() -> dict:
    """Return a full set of randomised browser-like headers."""
    ua = get_random_user_agent()
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": random.choice([
            "en-US,en;q=0.9",
            "en-GB,en;q=0.9",
            "en-US,en;q=0.9,am;q=0.8",
        ]),
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }


# ---------------------------------------------------------------------------
# 2. Human-like delay (no-op when delays disabled)
# ---------------------------------------------------------------------------
async def human_delay(
    min_seconds: float = 1.0,
    max_seconds: float = 4.0,
    label: str = "",
) -> None:
    """Sleep for a randomised duration. No-op when USE_SCRAPER_DELAYS is off."""
    if not _DELAYS_ENABLED:
        return
    delay = random.uniform(min_seconds, max_seconds)
    if label:
        logger.debug(f"[AntiBlock] {label} — sleeping {delay:.1f}s")
    await asyncio.sleep(delay)


# ---------------------------------------------------------------------------
# 3. Per-platform cooldown tracker (no-op when delays disabled)
# ---------------------------------------------------------------------------
class PlatformCooldown:
    """Enforces a minimum interval between requests to the same platform.
    Completely skipped when USE_SCRAPER_DELAYS is off.
    """

    def __init__(self, min_interval_seconds: float = 30.0):
        self.min_interval = min_interval_seconds
        self._last_request: Dict[str, float] = {}

    async def wait(self, platform: str) -> None:
        """Wait if the last request was too recent. No-op when delays disabled."""
        if not _DELAYS_ENABLED:
            return
        last = self._last_request.get(platform, 0.0)
        elapsed = time.monotonic() - last
        if elapsed < self.min_interval:
            wait_time = self.min_interval - elapsed
            logger.info(
                f"[AntiBlock] Platform '{platform}' cooldown: "
                f"waiting {wait_time:.1f}s before next request."
            )
            await asyncio.sleep(wait_time)

    def mark(self, platform: str) -> None:
        """Record that a request was just made for *platform*."""
        self._last_request[platform] = time.monotonic()


# Shared singleton
platform_cooldown = PlatformCooldown(min_interval_seconds=30.0)


# ---------------------------------------------------------------------------
# 4. Exponential backoff retry (always active — retries real errors)
# ---------------------------------------------------------------------------
async def retry_with_backoff(
    coro_factory: Callable,
    max_retries: int = 3,
    base_delay: float = 5.0,
    max_delay: float = 60.0,
    retryable_status_codes: tuple = (429, 500, 502, 503, 504),
    label: str = "request",
):
    """Execute an async callable with exponential backoff on failure.

    This is ALWAYS active regardless of USE_SCRAPER_DELAYS — retrying
    on real server errors is not a delay, it's error handling.
    """
    for attempt in range(1, max_retries + 1):
        try:
            result = await coro_factory()
            return result
        except Exception as exc:
            status = getattr(exc, "status_code", None) or getattr(
                getattr(exc, "response", None), "status_code", None
            )
            if status and status not in retryable_status_codes:
                logger.error(f"[AntiBlock] {label} — non-retryable HTTP {status}: {exc}")
                raise

            delay = min(base_delay * (2 ** (attempt - 1)) + random.uniform(0, 2), max_delay)
            logger.warning(
                f"[AntiBlock] {label} — attempt {attempt}/{max_retries} failed: {exc}. "
                f"Retrying in {delay:.1f}s..."
            )
            await asyncio.sleep(delay)

    logger.error(f"[AntiBlock] {label} — all {max_retries} retries exhausted.")
    return None


# ---------------------------------------------------------------------------
# 5. Instaloader-specific request delay hook (no-op when delays disabled)
# ---------------------------------------------------------------------------
def patch_instaloader_sleep(loader) -> None:
    """Configure Instaloader's built-in rate-limit sleep.
    No-op when USE_SCRAPER_DELAYS is off (authenticated mode).
    """
    if not _DELAYS_ENABLED:
        return
    try:
        loader.context.sleep = True
        loader.context.quiet = True
        loader.context._rate_controller.query_waittime = lambda *_: random.uniform(4.0, 8.0)
    except AttributeError:
        logger.debug("[AntiBlock] Could not patch Instaloader sleep — using defaults.")

