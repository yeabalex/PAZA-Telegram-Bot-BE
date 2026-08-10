"""Redis Staging, Atomic Task Queue, and Feed Cache Manager."""

import json
import logging
from typing import Optional, Dict, Any
from app.core.config import settings

logger = logging.getLogger(__name__)

# Key naming conventions
STAGING_KEY_PREFIX = "staging:message:"
QUEUE_KEY = "queue:event_extraction"
FEED_KEY_PREFIX = "feed:events:"

DEDUP_KEY_PREFIX = "dedup:events:"

# Expiration defaults
STAGING_TTL_SECONDS = 3600  # 1 hour
FEED_EVENT_TTL_SECONDS = 30 * 86400  # 30 days


class RedisQueueManager:
    """Manages Redis staging keys, atomic task queue, and feed cache.
    
    Supports redis.asyncio or an in-memory fallback for local testing.
    """

    def __init__(self, redis_client=None):
        self._redis = redis_client
        self._in_memory_staging: Dict[str, str] = {}
        self._in_memory_queue: list = []
        self._in_memory_feed: Dict[str, str] = {}
        self._in_memory_dedup: Dict[str, str] = {}

    @classmethod
    async def create(cls, redis_url: Optional[str] = None) -> "RedisQueueManager":
        """Factory method to initialize Redis connection or fallback."""
        url = redis_url or settings.REDIS_URL
        try:
            import redis.asyncio as aioredis
            client = aioredis.from_url(url, decode_responses=True)
            await client.ping()
            logger.info("Successfully connected to Redis server.")
            return cls(redis_client=client)
        except Exception as e:
            logger.warning(f"Could not connect to Redis ({e}). Operating in resilient In-Memory Queue Mode.")
            return cls(redis_client=None)

    def generate_dedup_key(self, title: Optional[str], start_datetime: Optional[str], venue_name: Optional[str]) -> str:
        """Construct normalized deduplication key from event title, start date, and venue."""
        import re
        date_part = str(start_datetime)[:10] if start_datetime else "nodate"
        clean_title = re.sub(r'[^a-z0-9]', '', (title or "").lower())[:25]
        clean_venue = re.sub(r'[^a-z0-9]', '', (venue_name or "").lower())[:15]
        return f"{clean_title}:{date_part}:{clean_venue}"

    async def stage_message(
        self,
        task_id: str,
        raw_text: str,
        platform: str = "telegram",
        post_url: Optional[str] = None,
        channel_username: Optional[str] = None,
        message_id: Optional[str] = None,
        scraped_date: Optional[str] = None,
        image_url: Optional[str] = None,
        is_video: bool = False,
    ) -> None:
        """Stage raw message text & full metadata with expiration (Step 2)."""
        key = f"{STAGING_KEY_PREFIX}{task_id}"
        payload = json.dumps({
            "raw_text": raw_text,
            "platform": platform,
            "post_url": post_url,
            "channel_username": channel_username,
            "message_id": str(message_id) if message_id else None,
            "scraped_date": scraped_date,
            "image_url": image_url,
            "is_video": is_video,
        })
        if self._redis:
            await self._redis.set(key, payload, ex=STAGING_TTL_SECONDS)
        else:
            self._in_memory_staging[task_id] = payload

    async def push_task(self, task_id: str) -> None:
        """Push task ID into shared Redis queue (Step 2)."""
        if self._redis:
            await self._redis.lpush(QUEUE_KEY, task_id)
        else:
            self._in_memory_queue.insert(0, task_id)

    async def pop_task(self, timeout: int = 2) -> Optional[str]:
        """Atomically pop next task ID from queue (Step 3: Lock-free distribution)."""
        if self._redis:
            try:
                result = await self._redis.brpop(QUEUE_KEY, timeout=timeout)
                if result:
                    return result[1]
            except Exception as e:
                logger.error(f"Error during Redis BRPOP: {e}")
                raise RuntimeError(f"Error during Redis BRPOP: {e}") from e
        else:
            if self._in_memory_queue:
                return self._in_memory_queue.pop()
        return None

    async def get_staged_message(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Fetch raw message text and metadata from staging area."""
        key = f"{STAGING_KEY_PREFIX}{task_id}"
        data_str = None
        if self._redis:
            data_str = await self._redis.get(key)
        else:
            data_str = self._in_memory_staging.get(task_id)

        if not data_str:
            return None
        try:
            return json.loads(data_str)
        except Exception:
            return {"raw_text": data_str, "platform": "telegram", "post_url": None}

    async def delete_staged_message(self, task_id: str) -> None:
        """Delete temporary staged raw message key (Step 5 hygiene)."""
        key = f"{STAGING_KEY_PREFIX}{task_id}"
        if self._redis:
            await self._redis.delete(key)
        else:
            self._in_memory_staging.pop(task_id, None)

    async def save_feed_event(self, event_id: str, event_data: Dict[str, Any], ttl_seconds: int = FEED_EVENT_TTL_SECONDS) -> None:
        """Save structured event with zero-token cross-platform deduplication and link merging (Step 5)."""
        dedup_key = self.generate_dedup_key(
            title=event_data.get("title"),
            start_datetime=event_data.get("start_datetime"),
            venue_name=event_data.get("venue_name")
        )
        dedup_redis_key = f"{DEDUP_KEY_PREFIX}{dedup_key}"

        existing_event_id = None
        if self._redis:
            existing_event_id = await self._redis.get(dedup_redis_key)
        else:
            existing_event_id = self._in_memory_dedup.get(dedup_key)

        if existing_event_id:
            # Match found! Perform cross-platform source link merging
            existing_feed_key = f"{FEED_KEY_PREFIX}{existing_event_id}"
            existing_raw = None
            if self._redis:
                existing_raw = await self._redis.get(existing_feed_key)
            else:
                existing_raw = self._in_memory_feed.get(existing_event_id)

            if existing_raw:
                existing_payload = json.loads(existing_raw)
                merged_sources = existing_payload.get("sources", {})
                merged_sources.update(event_data.get("sources", {}))
                existing_payload["sources"] = merged_sources

                serialized = json.dumps(existing_payload, default=str)
                if self._redis:
                    await self._redis.set(existing_feed_key, serialized, ex=ttl_seconds)
                else:
                    self._in_memory_feed[existing_event_id] = serialized

                logger.info(f"CROSS-PLATFORM MERGE SUCCESS: Linked duplicate event from {list(event_data.get('sources', {}).keys())} into existing event [{existing_event_id}]. Active Sources: {list(merged_sources.keys())}")
                return

        # New event entry
        key = f"{FEED_KEY_PREFIX}{event_id}"
        serialized = json.dumps(event_data, default=str)
        if self._redis:
            await self._redis.set(key, serialized, ex=ttl_seconds)
            await self._redis.set(dedup_redis_key, event_id, ex=ttl_seconds)
        else:
            self._in_memory_feed[event_id] = serialized
            self._in_memory_dedup[dedup_key] = event_id

        logger.info(f"Saved new event [{event_id}] to Redis feed cache (Dedup Key: {dedup_key}, TTL: {round(ttl_seconds/3600, 1)}h).")


    async def close(self) -> None:
        """Close connection resources."""
        if self._redis:
            if hasattr(self._redis, "aclose"):
                await self._redis.aclose()
            else:
                await self._redis.close()
