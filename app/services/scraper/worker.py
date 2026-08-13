"""Extraction Worker Agent for Atomic Redis Queue Processing & Multi-LLM Parsing."""

import asyncio
import json
import logging
import os
from typing import Optional
from app.services.scraper.redis_queue import RedisQueueManager
from app.services.llm.router import LLMRouter

logger = logging.getLogger(__name__)


class ExtractionWorker:
    """Worker agent pulling task IDs from Redis queue and extracting structured event data via alternating LLMs."""

    def __init__(
        self,
        worker_id: str,
        queue_manager: RedisQueueManager,
        llm_router: Optional[LLMRouter] = None
    ):
        self.worker_id = worker_id
        self.queue_manager = queue_manager
        self.llm_router = llm_router or LLMRouter()
        self._running = False

    def _calculate_redis_ttl(self, start_dt_str: Optional[str], end_dt_str: Optional[str]) -> int:
        """Calculate Redis TTL in seconds so key expires 24 hours after the event end date/time."""
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        target_dt = None

        # Prefer end_datetime, fallback to start_datetime
        for dt_str in [end_dt_str, start_dt_str]:
            if dt_str:
                try:
                    cleaned = str(dt_str).replace("Z", "+00:00")
                    parsed = datetime.fromisoformat(cleaned)
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    target_dt = parsed
                    break
                except Exception:
                    pass

        if not target_dt:
            # Default fallback TTL: 24 hours (86,400 seconds)
            return 86400

        # Expiry is 24 hours (86,400s) AFTER the event end date/time
        expiration_dt = target_dt + timedelta(hours=24)
        ttl_seconds = int((expiration_dt - now).total_seconds())

        # Ensure minimum 1 hour (3600s) and maximum 30 days
        return max(3600, min(ttl_seconds, 30 * 86400))

    async def process_single_task(self, task_id: str) -> bool:
        """Process a single task from Redis queue (Steps 4 & 5)."""
        logger.info(f"Worker [{self.worker_id}] claimed task [{task_id}]")

        # Step 4: Fetch staged raw post text and all metadata
        staged_data = await self.queue_manager.get_staged_message(task_id)
        if not staged_data:
            logger.warning(f"Worker [{self.worker_id}] Task [{task_id}] has no staged data -> Skipping.")
            return False

        if isinstance(staged_data, dict):
            raw_text = staged_data.get("raw_text", "")
            platform = staged_data.get("platform", "telegram")
            post_url = staged_data.get("post_url")
            channel_username = staged_data.get("channel_username")
            message_id = staged_data.get("message_id")
            scraped_date = staged_data.get("scraped_date")
            image_url = staged_data.get("image_url")
            is_video = staged_data.get("is_video", False)
        else:
            raw_text = str(staged_data)
            platform = "telegram"
            post_url = None
            channel_username = None
            message_id = None
            scraped_date = None
            image_url = None
            is_video = False

        if not raw_text:
            return False

        # Transcribe video audio if post is a video (or IG/TikTok) and caption is short (< 150 chars)
        if (is_video or platform in ("instagram", "tiktok")) and post_url and len(raw_text.strip()) < 150:
            try:
                from app.services.transcriber.whisper import WhisperTranscriber
                transcriber = WhisperTranscriber()
                raw_text = await transcriber.transcribe_post_video_if_needed(
                    post_url=post_url,
                    current_caption=raw_text,
                    min_caption_len=150
                )
            except Exception as e:
                logger.warning(f"Audio transcription step skipped for task [{task_id}]: {e}")

        # Local Event Classifier Pre-Filter (saves LLM API tokens & time)
        from app.services.classifier.event_classifier import EventClassifier
        classifier = EventClassifier.get_instance()
        is_event_candidate, confidence_score, meta_info = classifier.classify(raw_text)

        if not is_event_candidate:
            logger.info(f"Worker [{self.worker_id}] LOCAL PRE-FILTER DROPPED: Task [{task_id}] is Non-Event (score: {confidence_score}). Skipping LLM call.")
            await self.queue_manager.delete_staged_message(task_id)
            return True

        # Build enriched context for LLM (includes metadata hints)
        llm_context = raw_text
        context_hints = []
        if platform:
            context_hints.append(f"Platform: {platform}")
        if channel_username:
            context_hints.append(f"Source: @{channel_username}")
        if post_url:
            context_hints.append(f"Post URL: {post_url}")
        if scraped_date:
            context_hints.append(f"Post Date: {scraped_date}")
        if context_hints:
            llm_context = f"[{' | '.join(context_hints)}]\n\n{raw_text}"

        # Extract event structure using alternating LLM providers
        events_list, provider_name = await self.llm_router.extract_events_alternating(llm_context)

        # Step 5: Storage & Cache Hygiene
        valid_events = [e for e in events_list if e and e.is_event]
        if valid_events:
            for sub_idx, event_result in enumerate(valid_events, start=1):
                sub_task_id = task_id if len(valid_events) == 1 else f"{task_id}_{sub_idx}"
                sources = {}
                if post_url:
                    sources[platform] = post_url

                event_payload = {
                    "event_id": sub_task_id,
                    "title": event_result.title,
                    "description": event_result.description,
                    "short_summary": event_result.short_summary,
                    "start_datetime": event_result.start_datetime,
                    "end_datetime": event_result.end_datetime,
                    "venue_name": event_result.venue_name,
                    "location_gps": event_result.location_gps,
                    "sub_city": event_result.sub_city,
                    "entrance_fee_etb": event_result.entrance_fee_etb,
                    "image_url": event_result.image_url or image_url,
                    "category": event_result.category,
                    "confidence_score": event_result.confidence_score,
                    "extracted_by": provider_name,
                    "sources": sources,
                    "source_channel": channel_username,
                    "source_platform": platform,
                    "source_message_id": message_id,
                    "scraped_date": scraped_date,
                    "raw_text": raw_text,
                }

                # Save to main Redis feed cache with dynamic TTL and deduplication merging
                ttl = self._calculate_redis_ttl(event_result.start_datetime, event_result.end_datetime)
                await self.queue_manager.save_feed_event(sub_task_id, event_payload, ttl_seconds=ttl)
                logger.info(f"Worker [{self.worker_id}] SUCCESS: Valid Event extracted via {provider_name} -> Saved to Feed ({sub_task_id}, TTL: {round(ttl/3600, 1)}h).")
        else:
            logger.info(f"Worker [{self.worker_id}] DROPPED: Post {task_id} classified as Non-Event by {provider_name}.")

        # Hygiene: Delete temporary staged raw message key
        await self.queue_manager.delete_staged_message(task_id)
        return True

    async def start(self, poll_timeout: int = 1, max_tasks: Optional[int] = None) -> None:
        """Start worker polling loop (Step 3: Lock-free atomic pops)."""
        self._running = True
        tasks_processed = 0
        logger.info(f"Worker [{self.worker_id}] started listening to Redis queue...")

        while self._running:
            task_id = await self.queue_manager.pop_task(timeout=poll_timeout)
            if task_id:
                await self.process_single_task(task_id)
                tasks_processed += 1
                if max_tasks and tasks_processed >= max_tasks:
                    logger.info(f"Worker [{self.worker_id}] reached max task limit ({max_tasks}). Stopping.")
                    break
            else:
                # Idle poll check
                await asyncio.sleep(0.1)

    def stop(self) -> None:
        """Stop worker execution loop."""
        self._running = False
