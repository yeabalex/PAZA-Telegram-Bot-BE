"""TikTok Scraper Module — powered by yt-dlp with anti-block protections."""

import abc
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup

from app.schemas.event import ScrapedMessage, TikTokAccountConfig
from app.services.scraper.anti_block import (
    get_random_headers,
    human_delay,
    platform_cooldown,
)

logger = logging.getLogger(__name__)


class YtDlpQuietLogger:
    """Quiet logger for yt-dlp to prevent noisy stderr dumps during rate limiting."""
    def debug(self, msg):
        pass
    def warning(self, msg):
        pass
    def error(self, msg):
        pass


class BaseTikTokScraper(abc.ABC):
    """Abstract TikTok scraper interface."""

    @abc.abstractmethod
    async def fetch_account_videos(
        self,
        config: TikTokAccountConfig,
        limit: int = 10,
    ) -> List[ScrapedMessage]:
        """Fetch videos/posts for a target TikTok handle or hashtag."""
        ...


class RealTikTokScraper(BaseTikTokScraper):
    """Real TikTok scraper using yt-dlp with full anti-block measures."""

    def _clean_caption(self, raw_caption: str) -> str:
        if not raw_caption:
            return ""
        return re.sub(r"\n\s*\n", "\n\n", raw_caption).strip()

    async def fetch_account_videos(
        self,
        config: TikTokAccountConfig,
        limit: int = 10,
    ) -> List[ScrapedMessage]:
        target = config.target_handle_or_hashtag.lstrip("@#").strip()
        is_hashtag = config.is_hashtag
        last_watermark_id = str(config.last_video_id or "0")
        url = (
            f"https://www.tiktok.com/tag/{target}"
            if is_hashtag
            else f"https://www.tiktok.com/@{target}"
        )
        logger.info(
            f"Fetching TikTok posts for {'#' if is_hashtag else '@'}{target} "
            f"(Watermark: {last_watermark_id}, Limit: {limit})..."
        )

        # ── Anti-block: enforce per-platform cooldown ──
        await platform_cooldown.wait("tiktok")

        # ── Anti-block: random human delay before scraping ──
        await human_delay(min_seconds=2.0, max_seconds=6.0, label=f"TT @{target}")

        raw_videos: List[tuple] = []

        from app.core.config import settings

        try:
            import yt_dlp

            random_headers = get_random_headers()
            http_headers = {"User-Agent": random_headers["User-Agent"]}
            if settings.TIKTOK_SESSION_ID:
                http_headers["Cookie"] = f"sessionid={settings.TIKTOK_SESSION_ID}; sessionid_ss={settings.TIKTOK_SESSION_ID}"

            ydl_opts = {
                "extract_flat": True,
                "skip_download": True,
                "quiet": True,
                "no_warnings": True,
                "logger": YtDlpQuietLogger(),
                "playlistend": limit,
                # Anti-block: random UA + sleep between requests
                "http_headers": http_headers,
                "sleep_interval_requests": 2,
                "max_sleep_interval": 5,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info and "entries" in info:
                    for entry in info["entries"]:
                        if not entry:
                            continue
                        v_id = str(entry.get("id") or "")
                        v_title = self._clean_caption(
                            entry.get("title") or entry.get("description") or ""
                        )
                        if v_id and len(v_title) > 5:
                            raw_videos.append((v_id, v_title))
        except Exception as e:
            logger.warning(f"yt-dlp extraction for {'#' if is_hashtag else '@'}{target}: {e}")

        # ── Fallback: direct web HTML + JSON script parsing ──
        if not raw_videos:
            try:
                random_headers = get_random_headers()
                tt_cookies = {}
                if settings.TIKTOK_SESSION_ID:
                    tt_cookies = {
                        "sessionid": settings.TIKTOK_SESSION_ID,
                        "sessionid_ss": settings.TIKTOK_SESSION_ID
                    }
                async with httpx.AsyncClient(
                    timeout=20.0,
                    follow_redirects=True,
                    headers=random_headers,
                    cookies=tt_cookies,
                ) as client:
                    await human_delay(1.0, 3.0, label=f"TT Web @{target}")

                    response = await client.get(url)
                    if response.status_code == 200:
                        soup = BeautifulSoup(response.text, "html.parser")

                        # 1. Parse JSON script rehydration payload (__UNIVERSAL_DATA_FOR_REHYDRATION__ or __NEXT_DATA__)
                        script_tag = soup.find("script", id="__UNIVERSAL_DATA_FOR_REHYDRATION__") or soup.find("script", id="__NEXT_DATA__")
                        if script_tag and script_tag.string:
                            try:
                                import json
                                js_data = json.loads(script_tag.string)
                                # Extract item list from universal data scope
                                default_scope = js_data.get("__DEFAULT_SCOPE__", {})
                                user_detail = default_scope.get("webapp.user-detail", {})
                                item_list = user_detail.get("itemList", []) or js_data.get("itemList", [])

                                for item in item_list[:limit]:
                                    v_id = str(item.get("id") or item.get("video", {}).get("id") or "")
                                    v_desc = self._clean_caption(item.get("desc") or item.get("video", {}).get("description") or "")
                                    if v_id:
                                        raw_videos.append((v_id, v_desc or f"TikTok Video {v_id} by @{target}"))
                            except Exception as js_err:
                                logger.debug(f"TikTok script JSON parse note: {js_err}")

                        # 2. Regex fallback for /video/ IDs in HTML
                        if not raw_videos:
                            video_ids = re.findall(r"/video/(\d+)", response.text)
                            unique_ids = list(dict.fromkeys(video_ids))
                            for v_id in unique_ids[:limit]:
                                v_url = f"https://www.tiktok.com/@{target}/video/{v_id}"
                                full_title = ""
                                try:
                                    # Try fetching individual video page for full caption
                                    v_res = await client.get(v_url)
                                    if v_res.status_code == 200:
                                        v_soup = BeautifulSoup(v_res.text, "html.parser")
                                        v_script = v_soup.find("script", id="__UNIVERSAL_DATA_FOR_REHYDRATION__") or v_soup.find("script", id="__NEXT_DATA__") or v_soup.find("script", id="SIGI_STATE")
                                        if v_script and v_script.string:
                                            try:
                                                import json
                                                v_js = json.loads(v_script.string)
                                                # Recursively find desc fields in json
                                                def _find_descs(obj):
                                                    res = []
                                                    if isinstance(obj, dict):
                                                        for k, val in obj.items():
                                                            if k == "desc" and isinstance(val, str) and len(val) > 5:
                                                                res.append(val)
                                                            else:
                                                                res.extend(_find_descs(val))
                                                    elif isinstance(obj, list):
                                                        for elem in obj:
                                                            res.extend(_find_descs(elem))
                                                    return res
                                                all_descs = _find_descs(v_js)
                                                if all_descs:
                                                    full_title = max(all_descs, key=len)
                                            except Exception:
                                                pass
                                        
                                        if not full_title:
                                            meta_desc = v_soup.find("meta", {"name": "description"}) or v_soup.find("meta", {"property": "og:description"})
                                            if meta_desc and meta_desc.get("content"):
                                                full_title = meta_desc.get("content", "")

                                    # Fix truncation checks for both '...' and unicode ellipsis '…' (\u2026)
                                    is_truncated = not full_title or full_title.endswith("...") or full_title.endswith("…") or "\u2026" in full_title[-3:]
                                    if is_truncated:
                                        try:
                                            # Try tikwm API for 100% full untruncated title
                                            tw_res = await client.post("https://tikwm.com/api/", data={"url": v_url})
                                            if tw_res.status_code == 200:
                                                tw_title = self._clean_caption(tw_res.json().get("data", {}).get("title") or "")
                                                if tw_title and not tw_title.endswith("…") and not tw_title.endswith("..."):
                                                    full_title = tw_title
                                        except Exception:
                                            pass

                                    if not full_title or full_title.endswith("...") or full_title.endswith("…"):
                                        oembed_url = f"https://www.tiktok.com/oembed?url={v_url}"
                                        o_res = await client.get(oembed_url)
                                        if o_res.status_code == 200:
                                            o_data = o_res.json()
                                            o_title = self._clean_caption(o_data.get("title", ""))
                                            if len(o_title) > len(full_title):
                                                full_title = o_title

                                    raw_videos.append((v_id, self._clean_caption(full_title) or f"TikTok Video {v_id} by @{target}"))
                                except Exception:
                                    raw_videos.append((v_id, f"TikTok Video {v_id} by @{target}"))
            except Exception as e:
                logger.error(
                    f"TikTok web fetch error for "
                    f"{'#' if is_hashtag else '@'}{target}: {e}"
                )

        # ── Mark cooldown timestamp ──
        platform_cooldown.mark("tiktok")

        # ── Watermark dedup + build ScrapedMessage list ──
        scraped_messages: List[ScrapedMessage] = []
        newest_video_id = last_watermark_id

        for idx, (video_id, text) in enumerate(raw_videos):
            if last_watermark_id != "0" and video_id == last_watermark_id:
                logger.info(
                    f"Reached watermark [{video_id}] for @{target}. Stopping."
                )
                break
            if len(scraped_messages) >= limit:
                logger.info(f"Reached limit ({limit}) for @{target}. Stopping.")
                break
            if idx == 0:
                newest_video_id = video_id

            # ── Anti-truncation: fetch full description if caption ends with "..." or "…" ──
            if text.endswith("...") or text.endswith("…") or "…" in text or len(text) < 120:
                try:
                    video_page_url = f"https://www.tiktok.com/@{target}/video/{video_id}"
                    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, headers=get_random_headers()) as client:
                        resp = await client.get(video_page_url)
                        if resp.status_code == 200:
                            descs = re.findall(r'\"desc\":\"([^\"]+)\"', resp.text)
                            clean_descs = [self._clean_caption(d) for d in descs if len(d) > 5 and not d.endswith("...") and not d.endswith("…")]
                            if clean_descs:
                                text = max(clean_descs, key=len)
                except Exception as uncut_err:
                    logger.debug(f"Un-truncate caption error for {video_id}: {uncut_err}")

            post_url = f"https://www.tiktok.com/@{target}/video/{video_id}"
            scraped_messages.append(
                ScrapedMessage(
                    channel_username=target,
                    message_id=video_id,
                    text=text,
                    date=datetime.now(timezone.utc),
                    platform="tiktok",
                    post_url=post_url,
                    is_video=True,
                )
            )

        config.last_video_id = newest_video_id
        logger.info(
            f"Fetched {len(scraped_messages)} TikTok videos for @{target} "
            f"(Updated Watermark: {config.last_video_id})."
        )
        return scraped_messages

    def save_tiktok_posts_to_json(
        self,
        messages: List[ScrapedMessage],
        filepath: str = "scraped_tiktok_posts.json",
    ) -> None:
        """Save scraped TikTok videos to a local JSON file for testing."""
        import json

        data = [
            {
                "platform": m.platform,
                "handle": m.channel_username,
                "video_id": m.message_id,
                "post_url": m.post_url,
                "date": m.date.isoformat() if m.date else None,
                "raw_caption": m.text,
            }
            for m in messages
        ]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(messages)} TikTok posts to {filepath}")

