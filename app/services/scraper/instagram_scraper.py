"""Instagram Scraper Module — powered by Instaloader with anti-block protections."""

import abc
import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

from app.schemas.event import ScrapedMessage, InstagramAccountConfig
from app.services.scraper.anti_block import (
    get_random_headers,
    human_delay,
    patch_instaloader_sleep,
    platform_cooldown,
)

logger = logging.getLogger(__name__)


class BaseInstagramScraper(abc.ABC):
    """Abstract Instagram scraper interface."""

    @abc.abstractmethod
    async def fetch_account_posts(
        self,
        config: InstagramAccountConfig,
        limit: int = 10,
    ) -> List[ScrapedMessage]:
        """Fetch posts for a target Instagram handle or hashtag."""
        ...


class RealInstagramScraper(BaseInstagramScraper):
    """Real Instagram scraper using Instaloader with full anti-block measures."""

    def _clean_caption(self, raw_caption: str) -> str:
        if not raw_caption:
            return ""
        return re.sub(r"\n\s*\n", "\n\n", raw_caption).strip()

    async def fetch_account_posts(
        self,
        config: InstagramAccountConfig,
        limit: int = 10,
    ) -> List[ScrapedMessage]:
        target = config.target_handle_or_hashtag.lstrip("@#").strip()
        is_hashtag = config.is_hashtag
        last_watermark_id = str(config.last_post_id or "0")
        logger.info(
            f"Fetching Instagram posts for {'#' if is_hashtag else '@'}{target} "
            f"(Watermark: {last_watermark_id}, Limit: {limit})..."
        )

        # ── Anti-block: enforce per-platform cooldown ──
        await platform_cooldown.wait("instagram")

        # ── Anti-block: random human delay before scraping ──
        await human_delay(min_seconds=2.0, max_seconds=5.0, label=f"IG @{target}")

        raw_posts: List[tuple] = []
        from app.core.config import settings
        import instaloader

        try:
            L = instaloader.Instaloader(
                download_pictures=False,
                download_videos=False,
                download_video_thumbnails=False,
                download_geotags=False,
                download_comments=False,
                save_metadata=False,
                max_connection_attempts=1,
                quiet=True,
            )

            # ── Anti-block: randomise Instaloader's User-Agent ──
            random_headers = get_random_headers()
            random_headers["X-IG-App-ID"] = "936619743392459"
            L.context._session.headers.update(random_headers)

            # ── Anti-block: patch Instaloader's internal request sleep ──
            patch_instaloader_sleep(L)

            # ── Auth Stage 1: Check session file across possible paths ──
            loaded_session = False
            ig_user = getattr(settings, "INSTAGRAM_USERNAME", None) or os.getenv("INSTAGRAM_USERNAME")
            ig_pass = getattr(settings, "INSTAGRAM_PASSWORD", None) or os.getenv("INSTAGRAM_PASSWORD")

            if ig_user:
                possible_paths = [
                    None,
                    f"/home/deployer/.config/instaloader/session-{ig_user}",
                    f"/root/.config/instaloader/session-{ig_user}",
                    f"/app/.config/instaloader/session-{ig_user}",
                ]
                for path in possible_paths:
                    try:
                        if path:
                            if os.path.exists(path):
                                L.load_session_from_file(ig_user, filename=path)
                                loaded_session = True
                                logger.info(f"Successfully loaded native Instaloader session from path '{path}'")
                                break
                        else:
                            L.load_session_from_file(ig_user)
                            loaded_session = True
                            logger.info(f"Successfully loaded native Instaloader session for '{ig_user}'")
                            break
                    except Exception:
                        continue

            # ── Auth Stage 2: Fallback to sessionid cookie & bind context username ──
            if not loaded_session and settings.INSTAGRAM_SESSION_ID:
                try:
                    import urllib.parse
                    raw_sid = settings.INSTAGRAM_SESSION_ID
                    unquoted_sid = urllib.parse.unquote(raw_sid)
                    ds_user_id = unquoted_sid.split(":")[0] if ":" in unquoted_sid else (unquoted_sid.split("%3A")[0] if "%3A" in unquoted_sid else "")

                    L.context._session.cookies.set(
                        "sessionid",
                        unquoted_sid,
                        domain=".instagram.com",
                    )
                    if ds_user_id:
                        L.context._session.cookies.set(
                            "ds_user_id",
                            ds_user_id,
                            domain=".instagram.com",
                        )
                    if ig_user:
                        L.context.username = ig_user
                    elif ds_user_id:
                        L.context.username = f"user_{ds_user_id}"

                    loaded_session = True
                    logger.info("Successfully injected sessionid cookie into Instaloader authenticated session context.")
                except Exception as c_err:
                    logger.warning(f"Failed to inject sessionid cookie: {c_err}")

            if not is_hashtag:
                profile = instaloader.Profile.from_username(L.context, target)
                count = 0
                for post in profile.get_posts():
                    shortcode = post.shortcode
                    caption = self._clean_caption(post.caption or "")
                    post_date = post.date_utc.replace(tzinfo=timezone.utc)
                    is_vid = getattr(post, "is_video", False)
                    raw_posts.append((shortcode, caption, post_date, is_vid))
                    count += 1
                    if count >= limit:
                        break
            else:
                hashtag = instaloader.Hashtag.from_name(L.context, target)
                count = 0
                for post in hashtag.get_posts():
                    shortcode = post.shortcode
                    caption = self._clean_caption(post.caption or "")
                    post_date = post.date_utc.replace(tzinfo=timezone.utc)
                    is_vid = getattr(post, "is_video", False)
                    raw_posts.append((shortcode, caption, post_date, is_vid))
                    count += 1
                    if count >= limit:
                        break

        except instaloader.exceptions.ConnectionException as e:
            logger.warning(
                f"[AntiBlock] Instagram rate-limit for @{target}: {e}.\n"
                f"💡 TIP: Instagram rate-limited this IP temporarily. Try again in a few minutes or verify sessionid."
            )
        except Exception as e:
            logger.error(f"Instaloader error fetching @{target}: {e}")

        # ── Direct HTTP API Fallback if Instaloader returned 0 posts ──
        if not raw_posts and settings.INSTAGRAM_SESSION_ID:
            try:
                import urllib.parse
                import httpx
                raw_sid = settings.INSTAGRAM_SESSION_ID
                unquoted_sid = urllib.parse.unquote(raw_sid)
                ds_user_id = unquoted_sid.split(":")[0] if ":" in unquoted_sid else ""

                api_headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                    "X-IG-App-ID": "936619743392459",
                    "X-ASBD-ID": "198387",
                    "Accept": "*/*",
                }
                api_cookies = {
                    "sessionid": unquoted_sid,
                    "ds_user_id": ds_user_id,
                }

                async with httpx.AsyncClient(headers=api_headers, cookies=api_cookies, timeout=15.0, follow_redirects=True) as client:
                    # 1. Resolve user PK via topsearch
                    user_pk = None
                    search_url = f"https://www.instagram.com/web/search/topsearch/?context=blended&query={target}"
                    r_search = await client.get(search_url)
                    if r_search.status_code == 200:
                        users = r_search.json().get("users", [])
                        for u in users:
                            usr = u.get("user", {})
                            if usr.get("username", "").lower() == target.lower():
                                user_pk = usr.get("pk")
                                break
                        if not user_pk and users:
                            user_pk = users[0].get("user", {}).get("pk")

                    # 2. Fetch user feed if PK resolved
                    if user_pk:
                        feed_url = f"https://www.instagram.com/api/v1/feed/user/{user_pk}/"
                        r_feed = await client.get(feed_url)
                        if r_feed.status_code == 200:
                            items = r_feed.json().get("items", [])
                            for item in items[:limit]:
                                sc = item.get("code")
                                caption_obj = item.get("caption") or {}
                                cap = self._clean_caption(caption_obj.get("text", "")) if isinstance(caption_obj, dict) else ""
                                ts = item.get("taken_at")
                                dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
                                is_vid = item.get("media_type") == 2 or item.get("is_video", False)
                                if sc:
                                    raw_posts.append((sc, cap, dt, is_vid))

                    # 3. Last fallback: web_profile_info
                    if not raw_posts:
                        api_url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={target}"
                        r = await client.get(api_url)
                        if r.status_code == 200:
                            data = r.json()
                            user_data = data.get("data", {}).get("user", {})
                            edges = user_data.get("edge_owner_to_timeline_media", {}).get("edges", [])
                            for e in edges[:limit]:
                                node = e.get("node", {})
                                sc = node.get("shortcode")
                                caption_edges = node.get("edge_media_to_caption", {}).get("edges", [])
                                cap = self._clean_caption(caption_edges[0]["node"]["text"]) if caption_edges else ""
                                is_vid = node.get("is_video", False)
                                if sc:
                                    raw_posts.append((sc, cap, datetime.now(timezone.utc), is_vid))
                if raw_posts:
                    logger.info(f"[Fallback] Direct IG API fallback fetched {len(raw_posts)} posts for @{target}")
            except Exception as fallback_err:
                logger.debug(f"Direct IG API fallback note for @{target}: {fallback_err}")

        # ── Mark cooldown timestamp ──
        platform_cooldown.mark("instagram")

        # ── Watermark dedup + build ScrapedMessage list ──
        scraped_messages: List[ScrapedMessage] = []
        newest_post_id = last_watermark_id

        for idx, (post_id, text, post_date, is_vid) in enumerate(raw_posts):
            if last_watermark_id != "0" and post_id == last_watermark_id:
                logger.info(f"Reached watermark [{post_id}] for @{target}. Stopping.")
                break
            if len(scraped_messages) >= limit:
                logger.info(f"Reached limit ({limit}) for @{target}. Stopping.")
                break
            if idx == 0:
                newest_post_id = post_id

            post_type_prefix = "reel" if is_vid else "p"
            scraped_messages.append(
                ScrapedMessage(
                    channel_username=target,
                    message_id=post_id,
                    text=text,
                    date=post_date,
                    platform="instagram",
                    post_url=f"https://www.instagram.com/{post_type_prefix}/{post_id}/",
                    is_video=is_vid,
                )
            )

        config.last_post_id = newest_post_id
        logger.info(
            f"Fetched {len(scraped_messages)} Instagram posts for @{target} "
            f"(Updated Watermark: {config.last_post_id})."
        )
        return scraped_messages

    def save_ig_posts_to_json(
        self,
        messages: List[ScrapedMessage],
        filepath: str = "scraped_ig_posts.json",
    ) -> None:
        """Save scraped IG posts to a local JSON file for testing."""
        import json

        data = [
            {
                "platform": m.platform,
                "handle": m.channel_username,
                "post_id": m.message_id,
                "post_url": m.post_url,
                "date": m.date.isoformat() if m.date else None,
                "raw_caption": m.text,
            }
            for m in messages
        ]
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(messages)} IG posts to {filepath}")

