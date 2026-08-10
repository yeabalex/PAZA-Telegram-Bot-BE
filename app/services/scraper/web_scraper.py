"""Web Search & Direct URL Scraper Module for Keyword Ingestion."""

import abc
import hashlib
import logging
import re
import urllib.parse
from datetime import datetime, timezone
from typing import List, Optional
import httpx
from bs4 import BeautifulSoup
from app.schemas.event import ScrapedMessage
from app.services.scraper.anti_block import get_random_headers, human_delay, platform_cooldown

logger = logging.getLogger(__name__)


class BaseWebScraper(abc.ABC):
    """Abstract web scraper interface."""

    @abc.abstractmethod
    async def fetch_keyword_search(
        self,
        keyword: str,
        limit: int = 10
    ) -> List[ScrapedMessage]:
        """Search the web for a keyword query and return matching scraped messages."""
        ...

    @abc.abstractmethod
    async def fetch_website_url(
        self,
        target_url: str,
        limit: int = 10
    ) -> List[ScrapedMessage]:
        """Scrape raw events/articles from a target website URL."""
        ...


class RealWebScraper(BaseWebScraper):
    """Real web scraper with DuckDuckGo HTML search & direct URL extraction."""

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        return re.sub(r"\n\s*\n", "\n\n", text).strip()

    def _generate_url_hash(self, url: str) -> str:
        return hashlib.md5(url.encode("utf-8")).hexdigest()[:12]

    async def fetch_keyword_search(
        self,
        keyword: str,
        limit: int = 10
    ) -> List[ScrapedMessage]:
        query = keyword.strip()
        logger.info(f"Executing web keyword search for '{query}' (limit: {limit})...")

        await platform_cooldown.wait("web")
        await human_delay(1.0, 3.0, label=f"Web search '{query}'")

        scraped_messages: List[ScrapedMessage] = []

        def _sync_ddg_search():
            try:
                from ddgs import DDGS
                with DDGS() as ddgs:
                    return list(ddgs.text(query, max_results=limit))
            except Exception as ex:
                logger.warning(f"ddgs search error: {ex}")
                return []

        try:
            import asyncio
            results = await asyncio.to_thread(_sync_ddg_search)
            for res in results:
                title = res.get("title", "")
                clean_url = res.get("href", "")
                snippet = res.get("body", "")

                if not clean_url or not title:
                    continue

                domain = urllib.parse.urlparse(clean_url).netloc or "web"
                url_hash = self._generate_url_hash(clean_url)
                combined_text = f"🌐 [Web Event Search: {title}]\n\n{snippet}\n\nSource Link: {clean_url}"

                scraped_messages.append(
                    ScrapedMessage(
                        channel_username=domain,
                        message_id=f"web_{url_hash}",
                        text=self._clean_text(combined_text),
                        date=datetime.now(timezone.utc),
                        platform="web",
                        post_url=clean_url
                    )
                )

        except Exception as e:
            logger.error(f"Error executing web search for '{query}': {e}")

        platform_cooldown.mark("web")
        logger.info(f"Web keyword search for '{query}' returned {len(scraped_messages)} results.")
        return scraped_messages

    async def fetch_website_url(
        self,
        target_url: str,
        limit: int = 10
    ) -> List[ScrapedMessage]:
        clean_url = target_url.strip()
        domain = urllib.parse.urlparse(clean_url).netloc or "web"
        logger.info(f"Fetching direct website content from {clean_url}...")

        await platform_cooldown.wait("web")
        await human_delay(1.0, 3.0, label=f"Web URL {clean_url}")

        scraped_messages: List[ScrapedMessage] = []
        headers = get_random_headers()

        try:
            async with httpx.AsyncClient(timeout=25.0, follow_redirects=True, headers=headers) as client:
                response = await client.get(clean_url)
                if response.status_code == 200:
                    soup = BeautifulSoup(response.text, "html.parser")

                    # Strip script/style tags
                    for s in soup(["script", "style", "nav", "footer", "header"]):
                        s.decompose()

                    # Find major content containers or body
                    articles = soup.find_all(["article", "section", "div"], class_=re.compile(r"(event|post|article|item|card)", re.I))
                    
                    if articles:
                        for idx, art in enumerate(articles[:limit]):
                            art_text = self._clean_text(art.get_text(separator="\n"))
                            if len(art_text) > 30:
                                url_hash = self._generate_url_hash(f"{clean_url}#{idx}")
                                scraped_messages.append(
                                    ScrapedMessage(
                                        channel_username=domain,
                                        message_id=f"web_{url_hash}",
                                        text=f"🌐 [Web Post @ {domain}]\n\n{art_text}",
                                        date=datetime.now(timezone.utc),
                                        platform="web",
                                        post_url=clean_url
                                    )
                                )
                    else:
                        # Fallback: Whole page body text snippet
                        body_text = self._clean_text(soup.body.get_text(separator="\n")) if soup.body else ""
                        if len(body_text) > 30:
                            url_hash = self._generate_url_hash(clean_url)
                            scraped_messages.append(
                                ScrapedMessage(
                                    channel_username=domain,
                                    message_id=f"web_{url_hash}",
                                    text=f"🌐 [Web Page @ {domain}]\n\n{body_text[:1500]}",
                                    date=datetime.now(timezone.utc),
                                    platform="web",
                                    post_url=clean_url
                                )
                            )
                else:
                    logger.warning(f"Web URL fetch HTTP {response.status_code} for {clean_url}.")

        except Exception as e:
            logger.error(f"Error fetching web URL {clean_url}: {e}")

        platform_cooldown.mark("web")
        logger.info(f"Website URL fetch for {clean_url} returned {len(scraped_messages)} content blocks.")
        return scraped_messages
