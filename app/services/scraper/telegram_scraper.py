"""Telegram Channel Scraper Module — with anti-block protections."""

import abc
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup

from app.schemas.event import ScrapedMessage
from app.services.scraper.anti_block import (
    get_random_headers,
    human_delay,
    platform_cooldown,
)

logger = logging.getLogger(__name__)


class BaseTelegramScraper(abc.ABC):
    """Abstract Telegram channel scraper interface."""

    @abc.abstractmethod
    async def fetch_channel_messages(
        self,
        channel_username: str,
        last_message_id: int = 0,
    ) -> List[ScrapedMessage]:
        """Fetch real live messages newer than last_message_id for a given public channel."""
        ...


class RealTelegramScraper(BaseTelegramScraper):
    """Real Telegram scraper with anti-block measures."""

    def _clean_html_text(self, text_element) -> str:
        """Clean HTML tags and convert <br> to newlines."""
        if not text_element:
            return ""
        for br in text_element.find_all(["br", "p"]):
            br.replace_with("\n" + br.text if br.name == "p" else "\n")
        raw_text = text_element.get_text()
        return re.sub(r"\n\s*\n", "\n\n", raw_text).strip()

    async def fetch_channel_messages(
        self,
        channel_username: str,
        last_message_id: int = 0,
        limit: int = 10,
    ) -> List[ScrapedMessage]:
        clean_username = channel_username.lstrip("@").strip()
        url = f"https://t.me/s/{clean_username}"
        logger.info(f"Fetching posts from Telegram @{clean_username} ({url})...")

        # ── Anti-block: enforce per-platform cooldown ──
        await platform_cooldown.wait("telegram")

        # ── Anti-block: random human delay before scraping ──
        await human_delay(min_seconds=1.0, max_seconds=3.0, label=f"TG @{clean_username}")

        # ── Anti-block: rotate User-Agent on every request ──
        random_headers = get_random_headers()

        async with httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
            headers=random_headers,
        ) as client:
            response = None
            for attempt in range(3):
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        break
                    logger.warning(
                        f"Attempt {attempt + 1}: HTTP {response.status_code} "
                        f"fetching @{clean_username}"
                    )
                    # ── Anti-block: backoff between retries ──
                    await human_delay(2.0 * (attempt + 1), 4.0 * (attempt + 1), label="TG retry")
                except Exception as e:
                    logger.warning(
                        f"Attempt {attempt + 1} network error "
                        f"fetching @{clean_username}: {e}"
                    )
                    await human_delay(2.0 * (attempt + 1), 4.0 * (attempt + 1), label="TG retry")

            if not response or response.status_code != 200:
                logger.error(
                    f"Failed to fetch Telegram @{clean_username} after 3 attempts."
                )
                platform_cooldown.mark("telegram")
                return []

            soup = BeautifulSoup(response.text, "html.parser")
            message_widgets = soup.find_all(
                "div", class_=re.compile(r"tgme_widget_message\b")
            )

            scraped_messages: List[ScrapedMessage] = []

            for widget in message_widgets:
                data_post = widget.get("data-post", "")
                if not data_post or "/" not in data_post:
                    continue

                try:
                    msg_id = int(data_post.split("/")[-1])
                except ValueError:
                    continue

                # Watermark filtering
                if last_message_id > 0 and msg_id <= last_message_id:
                    continue

                text_div = widget.find(
                    "div", class_=re.compile(r"tgme_widget_message_text\b")
                )
                if not text_div:
                    continue

                clean_text = self._clean_html_text(text_div)
                if not clean_text or len(clean_text) < 5:
                    continue

                time_elem = widget.find("time", datetime=True)
                msg_date = datetime.now(timezone.utc)
                if time_elem and time_elem.get("datetime"):
                    try:
                        msg_date = datetime.fromisoformat(
                            time_elem["datetime"].replace("Z", "+00:00")
                        )
                    except Exception:
                        pass

                scraped_messages.append(
                    ScrapedMessage(
                        channel_username=clean_username,
                        message_id=msg_id,
                        text=clean_text,
                        date=msg_date,
                    )
                )

            scraped_messages.sort(key=lambda m: m.message_id)
            scraped_messages = scraped_messages[-limit:] if scraped_messages else []

            logger.info(
                f"Fetched {len(scraped_messages)} posts for Telegram @{clean_username} "
                f"(watermark > {last_message_id}, limit={limit})."
            )

            # ── Mark cooldown timestamp ──
            platform_cooldown.mark("telegram")

            return scraped_messages

