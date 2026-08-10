"""Producer Task Service for Watermark Message Scraping, Pre-Filtering, and Staging."""

import logging
from typing import List
from app.schemas.event import (
    ChannelConfig,
    ScraperTarget,
    ScraperPlatform,
    TargetType,
    InstagramAccountConfig,
    TikTokAccountConfig,
)
from app.services.scraper.telegram_scraper import BaseTelegramScraper, RealTelegramScraper
from app.services.scraper.pre_filter import passes_pre_filter
from app.services.scraper.redis_queue import RedisQueueManager

logger = logging.getLogger(__name__)


class ScraperProducer:
    """Producer task orchestrating watermark checks, message fetching, pre-filtering, and Redis staging."""

    def __init__(
        self,
        queue_manager: RedisQueueManager,
        scraper: BaseTelegramScraper = None
    ):
        self.queue_manager = queue_manager
        self.scraper = scraper or RealTelegramScraper()


    async def run_producer_cycle(self, channels: List[ChannelConfig]) -> List[ChannelConfig]:
        """Execute one producer ingestion cycle over the configured channels array (Steps 1 & 2).
        
        Updates and returns the updated ChannelConfig array with updated watermarks.
        """
        logger.info(f"--- Starting Producer Cycle for {len(channels)} channels ---")
        staged_count = 0
        skipped_count = 0

        for config in channels:
            channel = config.channel_username
            last_id = config.last_message_id
            logger.info(f"Processing channel @{channel} (Current Watermark ID: {last_id})")

            messages = await self.scraper.fetch_channel_messages(
                channel_username=channel,
                last_message_id=last_id
            )

            max_seen_id = last_id

            for msg in messages:
                if msg.message_id > max_seen_id:
                    max_seen_id = msg.message_id

                # Step 2: Fast Pre-Filtering
                if not passes_pre_filter(msg.text):
                    logger.debug(f"Message {msg.task_id} failed pre-filter -> Skipped.")
                    skipped_count += 1
                    continue

                # Stage raw text & full metadata in Redis and push task ID to queue
                task_id = msg.task_id
                post_url = msg.post_url or f"https://t.me/s/{channel}/{msg.message_id}"
                await self.queue_manager.stage_message(
                    task_id=task_id,
                    raw_text=msg.text,
                    platform=msg.platform,
                    post_url=post_url,
                    channel_username=msg.channel_username,
                    message_id=str(msg.message_id),
                    scraped_date=msg.date.isoformat() if msg.date else None,
                    image_url=msg.image_url,
                )
                await self.queue_manager.push_task(task_id)
                staged_count += 1
                logger.info(f"Staged & queued task [{task_id}]")

            # Update channel watermark ID
            config.last_message_id = max_seen_id
            logger.info(f"Updated watermark for @{channel} -> New Watermark ID: {max_seen_id}")

        logger.info(f"--- Producer Cycle Complete: {staged_count} tasks queued, {skipped_count} posts filtered out ---")
        return channels

    async def run_instagram_producer_cycle(
        self,
        ig_configs: List[any],
        ig_scraper: any = None
    ) -> None:
        """Execute Instagram ingestion cycle across configured accounts/hashtags."""
        from app.services.scraper.instagram_scraper import RealInstagramScraper
        scraper = ig_scraper or RealInstagramScraper()
        logger.info(f"--- Starting Instagram Producer Cycle for {len(ig_configs)} targets ---")
        staged_count = 0

        for config in ig_configs:
            messages = await scraper.fetch_account_posts(config)
            for msg in messages:
                if not passes_pre_filter(msg.text):
                    continue
                task_id = msg.task_id
                await self.queue_manager.stage_message(
                    task_id=task_id,
                    raw_text=msg.text,
                    platform="instagram",
                    post_url=msg.post_url,
                    channel_username=msg.channel_username,
                    message_id=str(msg.message_id),
                    scraped_date=msg.date.isoformat() if msg.date else None,
                    image_url=msg.image_url,
                )
                await self.queue_manager.push_task(task_id)
                staged_count += 1
                logger.info(f"Staged & queued Instagram task [{task_id}]")

        logger.info(f"--- Instagram Producer Cycle Complete: {staged_count} tasks queued ---")

    async def run_tiktok_producer_cycle(
        self,
        tiktok_configs: List[any],
        tiktok_scraper: any = None
    ) -> None:
        """Execute TikTok ingestion cycle across configured accounts/hashtags."""
        from app.services.scraper.tiktok_scraper import RealTikTokScraper
        scraper = tiktok_scraper or RealTikTokScraper()
        logger.info(f"--- Starting TikTok Producer Cycle for {len(tiktok_configs)} targets ---")
        staged_count = 0

        for config in tiktok_configs:
            messages = await scraper.fetch_account_videos(config)
            for msg in messages:
                if not passes_pre_filter(msg.text):
                    continue
                task_id = msg.task_id
                await self.queue_manager.stage_message(
                    task_id=task_id,
                    raw_text=msg.text,
                    platform="tiktok",
                    post_url=msg.post_url,
                    channel_username=msg.channel_username,
                    message_id=str(msg.message_id),
                    scraped_date=msg.date.isoformat() if msg.date else None,
                    image_url=msg.image_url,
                )
                await self.queue_manager.push_task(task_id)
                staged_count += 1
                logger.info(f"Staged & queued TikTok task [{task_id}]")

        logger.info(f"--- TikTok Producer Cycle Complete: {staged_count} tasks queued ---")

    # -----------------------------------------------------------------------
    # Unified producer — routes by platform + target_type
    # -----------------------------------------------------------------------
    async def run_unified_producer_cycle(
        self,
        targets: List[ScraperTarget],
    ) -> List[ScraperTarget]:
        """Execute a single producer cycle across all targets, routing by platform + target_type.

        Returns the updated targets list with refreshed watermarks.
        """
        active_targets = [t for t in targets if t.is_active]
        logger.info(f"=== Unified Producer Cycle: {len(active_targets)} active targets ===")
        staged_total = 0

        for target in active_targets:
            platform = target.platform.value
            ttype = target.target_type.value
            value = target.value
            logger.info(f"Processing [{platform}:{ttype}] '{value}' (watermark: {target.last_watermark})")

            messages = []

            try:
                if target.platform == ScraperPlatform.WEB or target.target_type == TargetType.KEYWORD:
                    from app.services.scraper.web_scraper import RealWebScraper
                    web_scraper = RealWebScraper()
                    if target.target_type == TargetType.KEYWORD:
                        messages = await web_scraper.fetch_keyword_search(value, limit=target.max_posts)
                    else:
                        messages = await web_scraper.fetch_website_url(value, limit=target.max_posts)

                elif target.platform == ScraperPlatform.TELEGRAM:
                    messages = await self.scraper.fetch_channel_messages(
                        channel_username=value,
                        last_message_id=int(target.last_watermark) if target.last_watermark != "0" else 0,
                        limit=target.max_posts,
                    )
                    # Update watermark to max message_id
                    if messages:
                        max_id = max(m.message_id for m in messages)
                        target.last_watermark = str(max_id)

                elif target.platform == ScraperPlatform.INSTAGRAM:
                    from app.services.scraper.instagram_scraper import RealInstagramScraper
                    ig_config = InstagramAccountConfig(
                        target_handle_or_hashtag=value,
                        last_post_id=target.last_watermark,
                        is_hashtag=(target.target_type == TargetType.HASHTAG),
                    )
                    ig_scraper = RealInstagramScraper()
                    messages = await ig_scraper.fetch_account_posts(ig_config, limit=target.max_posts)
                    target.last_watermark = ig_config.last_post_id

                elif target.platform == ScraperPlatform.TIKTOK:
                    from app.services.scraper.tiktok_scraper import RealTikTokScraper
                    tt_config = TikTokAccountConfig(
                        target_handle_or_hashtag=value,
                        last_video_id=target.last_watermark,
                        is_hashtag=(target.target_type == TargetType.HASHTAG),
                    )
                    tt_scraper = RealTikTokScraper()
                    messages = await tt_scraper.fetch_account_videos(tt_config, limit=target.max_posts)
                    target.last_watermark = tt_config.last_video_id

            except Exception as e:
                logger.error(f"Error scraping [{platform}:{ttype}] '{value}': {e}")
                continue

            # Stage & queue each message
            for msg in messages:
                if not passes_pre_filter(msg.text):
                    continue
                task_id = msg.task_id
                post_url = msg.post_url
                if not post_url and platform == "telegram":
                    post_url = f"https://t.me/s/{value}/{msg.message_id}"

                await self.queue_manager.stage_message(
                    task_id=task_id,
                    raw_text=msg.text,
                    platform=platform,
                    post_url=post_url,
                    channel_username=msg.channel_username,
                    message_id=str(msg.message_id),
                    scraped_date=msg.date.isoformat() if msg.date else None,
                    image_url=msg.image_url,
                    is_video=getattr(msg, "is_video", False),
                )
                await self.queue_manager.push_task(task_id)
                staged_total += 1
                logger.info(f"Staged [{platform}:{ttype}] task [{task_id}]")

        logger.info(f"=== Unified Producer Cycle Complete: {staged_total} tasks queued ===")
        return targets
