"""Redis Storage Manager for Extracted Events with TTL (24 Hours after Event End Time)."""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
import redis.asyncio as redis
from app.core.config import settings

logger = logging.getLogger(__name__)


class RedisEventStorage:
    """Stores extracted event JSON in Redis/Valkey with TTL set to 24h post-event end."""

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or settings.REDIS_URL
        self._client: Optional[redis.Redis] = None

    async def get_client(self) -> redis.Redis:
        """Get or initialize async Redis client."""
        if self._client is None:
            self._client = redis.Redis.from_url(
                self.redis_url,
                decode_responses=True,
                socket_timeout=15.0,
                socket_connect_timeout=15.0,
                socket_keepalive=True
            )
        return self._client

    @staticmethod
    def calculate_ttl_seconds(start_dt_str: Optional[str], end_dt_str: Optional[str]) -> int:
        """Calculate TTL in seconds: 24 Hours AFTER end_datetime (or start_datetime + 48h fallback).
        
        Minimum TTL is 3600 seconds (1 hour) to ensure short-lived events remain queryable.
        """
        now = datetime.now(timezone.utc)
        expiration_time: Optional[datetime] = None

        # 1. Try parsing end_datetime
        if end_dt_str:
            try:
                dt = datetime.fromisoformat(end_dt_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                expiration_time = dt + timedelta(hours=24)
            except Exception as e:
                logger.debug(f"Could not parse end_datetime [{end_dt_str}]: {e}")

        # 2. Fallback to start_datetime + 48h
        if expiration_time is None and start_dt_str:
            try:
                dt = datetime.fromisoformat(start_dt_str)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                expiration_time = dt + timedelta(hours=48)
            except Exception as e:
                logger.debug(f"Could not parse start_datetime [{start_dt_str}]: {e}")

        # 3. Ultimate fallback: 24 hours from right now
        if expiration_time is None:
            expiration_time = now + timedelta(hours=24)

        ttl_seconds = int((expiration_time - now).total_seconds())
        # Enforce minimum 1 hour (3600s) and max 30 days
        return max(3600, min(ttl_seconds, 30 * 86400))

    async def save_event(
        self,
        platform: str,
        post_id: str,
        event_dict: Dict[str, Any],
        raw_metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Save extracted event JSON to Redis with calculated TTL."""
        try:
            client = await self.get_client()
            redis_key = f"event:{platform}:{post_id}"

            payload = {
                "platform": platform,
                "post_id": post_id,
                "stored_at": datetime.now(timezone.utc).isoformat(),
                "event": event_dict,
                "metadata": raw_metadata or {}
            }

            start_dt = event_dict.get("start_datetime")
            end_dt = event_dict.get("end_datetime")
            ttl_seconds = self.calculate_ttl_seconds(start_dt, end_dt)

            payload_json = json.dumps(payload, ensure_ascii=False)
            await client.setex(redis_key, ttl_seconds, payload_json)

            hours = round(ttl_seconds / 3600, 1)
            logger.info(f"Saved event to Redis [{redis_key}] with TTL={ttl_seconds}s ({hours}h): '{event_dict.get('title')}'")
            return True
        except Exception as e:
            logger.error(f"Failed to save event [{platform}:{post_id}] to Redis: {e}")
            raise RuntimeError(f"Failed to save event [{platform}:{post_id}] to Redis: {e}") from e

    async def get_event(self, platform: str, post_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve stored event JSON from Redis."""
        try:
            client = await self.get_client()
            redis_key = f"event:{platform}:{post_id}"
            raw = await client.get(redis_key)
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.error(f"Failed to fetch event [{platform}:{post_id}] from Redis: {e}")
            raise RuntimeError(f"Failed to fetch event [{platform}:{post_id}] from Redis: {e}") from e
        return None

    _cached_events: Optional[list] = None
    _last_cache_time: float = 0.0

    async def get_all_active_events(self) -> list[Dict[str, Any]]:
        """Retrieve all currently active stored event JSON objects from Redis (with 15s memory cache)."""
        import time
        now = time.time()
        if RedisEventStorage._cached_events is not None and (now - RedisEventStorage._last_cache_time) < 15.0:
            return RedisEventStorage._cached_events

        events = []
        try:
            client = await self.get_client()
            keys = await client.keys("event:*")
            if keys:
                raw_items = await client.mget(keys)
                for raw in raw_items:
                    if raw:
                        events.append(json.loads(raw))
            RedisEventStorage._cached_events = events
            RedisEventStorage._last_cache_time = now
            return events
        except Exception as e:
            logger.error(f"Failed to fetch active events from Redis: {e}")
            raise RuntimeError(f"Failed to fetch active events from Redis: {e}") from e

    async def close(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
