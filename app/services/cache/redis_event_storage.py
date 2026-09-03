"""Redis Storage Manager for Extracted Events with TTL, Past/Upcoming Partitioning, and Hygiene."""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List
import redis.asyncio as redis
from app.core.config import settings

logger = logging.getLogger(__name__)

EAT_TIMEZONE = timezone(timedelta(hours=3))


def parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Parse ISO datetime string into timezone-aware datetime (defaulting naive to UTC+3 East Africa Time)."""
    if not dt_str:
        return None
    try:
        clean = str(dt_str).strip().replace("Z", "+00:00").replace("z", "+00:00").replace(" ", "T")
        # Handle date-only "YYYY-MM-DD"
        if len(clean) == 10 and clean.count("-") == 2:
            clean += "T23:59:59"
        parsed = datetime.fromisoformat(clean)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=EAT_TIMEZONE)
        return parsed
    except Exception:
        return None


class RedisEventStorage:
    """Stores extracted event JSON in Redis/Valkey with TTL and Upcoming/Past filtering."""

    _cached_events: Optional[list] = None
    _last_cache_time: float = 0.0

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
    def is_event_passed(
        start_dt_str: Optional[str],
        end_dt_str: Optional[str],
        reference_time: Optional[datetime] = None
    ) -> bool:
        """Determine if an event has already concluded based on end_datetime or start_datetime.
        
        Rules:
        1. If end_datetime is provided and parseable, check if parsed end_datetime < reference_time.
        2. If only start_datetime is provided:
           - If date-only format (YYYY-MM-DD), event is considered active until end of that day (23:59:59 EAT).
           - If datetime format, event is considered active until 23:59:59 of that day or start + 4h (whichever is later).
           - If that effective cutoff < reference_time, the event has passed.
        3. If neither datetime is parseable (e.g. 'Upcoming', None), do NOT consider it passed.
        """
        now = reference_time or datetime.now(EAT_TIMEZONE)
        if now.tzinfo is None:
            now = now.replace(tzinfo=EAT_TIMEZONE)

        parsed_end = parse_iso_datetime(end_dt_str)
        if parsed_end:
            return parsed_end < now

        parsed_start = parse_iso_datetime(start_dt_str)
        if parsed_start:
            end_of_day = parsed_start.replace(hour=23, minute=59, second=59, microsecond=0)
            effective_end = max(end_of_day, parsed_start + timedelta(hours=4))
            return effective_end < now

        return False

    @classmethod
    def calculate_ttl_seconds(
        cls,
        start_dt_str: Optional[str],
        end_dt_str: Optional[str],
        past_retention_days: int = 7
    ) -> int:
        """Calculate TTL in seconds:
        
        - For upcoming events: 24 Hours AFTER end_datetime (or start + 48h).
        - For past events: retained for `past_retention_days` (default 7 days) post-conclusion so they appear in 'Past Events'.
        - If concluded more than 14 days ago: returns 0 (stale/expired, do not store).
        """
        now = datetime.now(EAT_TIMEZONE)
        is_passed = cls.is_event_passed(start_dt_str, end_dt_str, reference_time=now)

        parsed_end = parse_iso_datetime(end_dt_str)
        parsed_start = parse_iso_datetime(start_dt_str)
        event_dt = parsed_end or parsed_start

        if is_passed:
            if event_dt:
                # How long ago did it conclude?
                age_seconds = (now - event_dt).total_seconds()
                if age_seconds > (14 * 86400):
                    # Older than 14 days is stale -> do not store
                    return 0
                remaining_retention = int((past_retention_days * 86400) - age_seconds)
                return max(3600, min(remaining_retention, past_retention_days * 86400))
            return 86400  # Fallback 1 day for past events with unknown date

        # Upcoming event TTL: 24h after end or 48h after start
        if parsed_end:
            expiration_time = parsed_end + timedelta(hours=24)
        elif parsed_start:
            expiration_time = parsed_start + timedelta(hours=48)
        else:
            expiration_time = now + timedelta(hours=24)

        ttl_seconds = int((expiration_time - now).total_seconds())
        return max(3600, min(ttl_seconds, 30 * 86400))

    async def save_event(
        self,
        platform: str,
        post_id: str,
        event_dict: Dict[str, Any],
        raw_metadata: Optional[Dict[str, Any]] = None,
        allow_recent_past: bool = True
    ) -> bool:
        """Save extracted event JSON to Redis with calculated TTL and is_passed flag.
        
        If allow_recent_past is True, recent past events (concluded within 14 days) are stored
        with a 7-day TTL so they appear in the 'Past Events' section.
        Events concluded > 14 days ago are discarded.
        """
        start_dt = event_dict.get("start_datetime")
        end_dt = event_dict.get("end_datetime")
        title = event_dict.get("title") or "Untitled Event"

        is_passed = self.is_event_passed(start_dt, end_dt)
        if is_passed and not allow_recent_past:
            logger.info(f"Skipping passed event [{platform}:{post_id}]: '{title}' has already passed.")
            return False

        ttl_seconds = self.calculate_ttl_seconds(start_dt, end_dt)
        if ttl_seconds <= 0:
            logger.info(f"Skipping stale event [{platform}:{post_id}]: '{title}' (concluded > 14 days ago).")
            return False

        try:
            client = await self.get_client()
            redis_key = f"event:{platform}:{post_id}"

            event_dict_copy = dict(event_dict)
            event_dict_copy["is_passed"] = is_passed

            payload = {
                "platform": platform,
                "post_id": post_id,
                "stored_at": datetime.now(timezone.utc).isoformat(),
                "event": event_dict_copy,
                "metadata": raw_metadata or {}
            }

            payload_json = json.dumps(payload, ensure_ascii=False)
            await client.setex(redis_key, ttl_seconds, payload_json)

            # Invalidate in-memory cache
            RedisEventStorage._cached_events = None

            hours = round(ttl_seconds / 3600, 1)
            status_tag = "PAST" if is_passed else "UPCOMING"
            logger.info(f"Saved {status_tag} event to Redis [{redis_key}] TTL={ttl_seconds}s ({hours}h): '{title}'")
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

    async def get_all_active_events(self, timeframe: str = "upcoming") -> list[Dict[str, Any]]:
        """Retrieve stored event JSON objects from Redis filtered by timeframe.
        
        timeframe options:
        - 'upcoming' (default): Returns only events whose dates have NOT yet passed.
        - 'past': Returns only events whose dates have concluded.
        - 'all': Returns all active Redis events (both upcoming and recent past).
        """
        import time
        now_ts = time.time()
        raw_events = []

        if RedisEventStorage._cached_events is not None and (now_ts - RedisEventStorage._last_cache_time) < 15.0:
            raw_events = RedisEventStorage._cached_events
        else:
            try:
                client = await self.get_client()
                keys = await client.keys("event:*")
                if keys:
                    raw_items = await client.mget(keys)
                    for raw in raw_items:
                        if not raw:
                            continue
                        try:
                            item = json.loads(raw)
                            raw_events.append(item)
                        except Exception as parse_err:
                            logger.warning(f"Could not parse Redis event JSON: {parse_err}")
                RedisEventStorage._cached_events = raw_events
                RedisEventStorage._last_cache_time = now_ts
            except Exception as e:
                logger.error(f"Failed to fetch active events from Redis: {e}")
                raise RuntimeError(f"Failed to fetch active events from Redis: {e}") from e

        # Filter by timeframe
        results = []
        for item in raw_events:
            evt = item.get("event", {})
            start_dt = evt.get("start_datetime")
            end_dt = evt.get("end_datetime")
            is_passed = self.is_event_passed(start_dt, end_dt)

            if timeframe == "upcoming" and is_passed:
                continue
            if timeframe == "past" and not is_passed:
                continue

            results.append(item)

        return results

    async def cleanup_passed_events(self, max_age_days: int = 7) -> Dict[str, Any]:
        """Scan Redis for passed events and delete expired ones.
        
        Parameters:
        - max_age_days: If > 0, deletes passed events that ended more than `max_age_days` days ago.
                        If 0, deletes ALL passed events regardless of age.
        """
        client = await self.get_client()
        cleaned_events: list[Dict[str, Any]] = []
        scanned_count = 0
        cleaned_count = 0
        now = datetime.now(EAT_TIMEZONE)

        # 1. Clean 'event:*' keys
        event_keys = await client.keys("event:*")
        scanned_count += len(event_keys)

        if event_keys:
            raw_items = await client.mget(event_keys)
            keys_to_delete = []

            for key, raw in zip(event_keys, raw_items):
                if not raw:
                    keys_to_delete.append(key)
                    continue
                try:
                    data = json.loads(raw)
                    evt = data.get("event", {})
                    start_dt = evt.get("start_datetime")
                    end_dt = evt.get("end_datetime")
                    title = evt.get("title") or "Unknown"

                    if self.is_event_passed(start_dt, end_dt, reference_time=now):
                        parsed_dt = parse_iso_datetime(end_dt) or parse_iso_datetime(start_dt)
                        should_delete = False
                        if max_age_days == 0:
                            should_delete = True
                        elif parsed_dt:
                            age_days = (now - parsed_dt).total_seconds() / 86400
                            if age_days >= max_age_days:
                                should_delete = True
                        else:
                            should_delete = True

                        if should_delete:
                            keys_to_delete.append(key)
                            cleaned_events.append({
                                "key": key,
                                "title": title,
                                "start_datetime": start_dt,
                                "end_datetime": end_dt,
                                "platform": data.get("platform")
                            })
                except Exception as parse_err:
                    logger.warning(f"Could not parse event key [{key}] during cleanup: {parse_err}")

            if keys_to_delete:
                await client.delete(*keys_to_delete)
                cleaned_count += len(keys_to_delete)
                logger.info(f"Cleaned up {len(keys_to_delete)} passed events from Redis ('event:*').")

        # 2. Clean 'feed:events:*' keys if any exist
        feed_keys = await client.keys("feed:events:*")
        scanned_count += len(feed_keys)

        if feed_keys:
            raw_feed_items = await client.mget(feed_keys)
            feed_keys_to_delete = []

            for key, raw in zip(feed_keys, raw_feed_items):
                if not raw:
                    feed_keys_to_delete.append(key)
                    continue
                try:
                    data = json.loads(raw)
                    start_dt = data.get("start_datetime")
                    end_dt = data.get("end_datetime")
                    title = data.get("title") or "Unknown"

                    if self.is_event_passed(start_dt, end_dt, reference_time=now):
                        parsed_dt = parse_iso_datetime(end_dt) or parse_iso_datetime(start_dt)
                        should_delete = False
                        if max_age_days == 0:
                            should_delete = True
                        elif parsed_dt:
                            age_days = (now - parsed_dt).total_seconds() / 86400
                            if age_days >= max_age_days:
                                should_delete = True
                        else:
                            should_delete = True

                        if should_delete:
                            feed_keys_to_delete.append(key)
                            cleaned_events.append({
                                "key": key,
                                "title": title,
                                "start_datetime": start_dt,
                                "end_datetime": end_dt,
                                "platform": data.get("source_platform")
                            })
                except Exception as parse_err:
                    logger.warning(f"Could not parse feed key [{key}] during cleanup: {parse_err}")

            if feed_keys_to_delete:
                await client.delete(*feed_keys_to_delete)
                cleaned_count += len(feed_keys_to_delete)
                logger.info(f"Cleaned up {len(feed_keys_to_delete)} passed feed events from Redis ('feed:events:*').")

        # Invalidate in-memory cache
        RedisEventStorage._cached_events = None
        RedisEventStorage._last_cache_time = 0.0

        remaining_count = max(0, scanned_count - cleaned_count)
        summary = {
            "status": "success",
            "max_age_days": max_age_days,
            "scanned_count": scanned_count,
            "cleaned_count": cleaned_count,
            "remaining_count": remaining_count,
            "cleaned_events": cleaned_events
        }
        logger.info(f"Redis cleanup completed: scanned {scanned_count}, cleaned {cleaned_count}, remaining {remaining_count}")
        return summary

    async def close(self):
        """Close Redis connection."""
        if self._client:
            await self._client.close()
            self._client = None
