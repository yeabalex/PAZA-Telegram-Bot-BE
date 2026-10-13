"""Automated Unit & Integration Tests for Passed Events Filtering, Upcoming/Past Partitioning, and Cleanup."""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.config import settings
from app.services.cache.redis_event_storage import (
    RedisEventStorage,
    parse_iso_datetime,
    EAT_TIMEZONE
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("TestEventCleanup")


async def test_parse_iso_datetime():
    print("Testing parse_iso_datetime...")
    assert parse_iso_datetime(None) is None
    assert parse_iso_datetime("") is None
    assert parse_iso_datetime("Invalid Date String") is None

    # Date only format
    dt = parse_iso_datetime("2026-09-01")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 9 and dt.day == 1
    assert dt.hour == 23 and dt.minute == 59 and dt.second == 59
    assert dt.tzinfo == EAT_TIMEZONE

    # Timezone aware with Z
    dt_z = parse_iso_datetime("2026-09-01T15:00:00Z")
    assert dt_z is not None
    assert dt_z.tzinfo == timezone.utc

    # Naive ISO string defaults to EAT
    dt_naive = parse_iso_datetime("2026-09-01T20:00:00")
    assert dt_naive is not None
    assert dt_naive.tzinfo == EAT_TIMEZONE
    print("✓ parse_iso_datetime tests passed.")


async def test_is_event_passed():
    print("Testing is_event_passed...")
    ref_time = datetime(2026, 9, 3, 18, 0, 0, tzinfo=EAT_TIMEZONE)

    # 1. Concluded yesterday
    assert RedisEventStorage.is_event_passed(
        start_dt_str="2026-09-02T18:00:00",
        end_dt_str="2026-09-02T22:00:00",
        reference_time=ref_time
    ) is True

    # 2. Date-only yesterday
    assert RedisEventStorage.is_event_passed(
        start_dt_str="2026-09-02",
        end_dt_str=None,
        reference_time=ref_time
    ) is True

    # 3. Future event tomorrow
    assert RedisEventStorage.is_event_passed(
        start_dt_str="2026-09-04T18:00:00",
        end_dt_str="2026-09-04T22:00:00",
        reference_time=ref_time
    ) is False

    # 4. Ended 2 hours ago today
    assert RedisEventStorage.is_event_passed(
        start_dt_str="2026-09-03T12:00:00",
        end_dt_str="2026-09-03T16:00:00",
        reference_time=ref_time
    ) is True

    # 5. Happening tonight (starts at 20:00)
    assert RedisEventStorage.is_event_passed(
        start_dt_str="2026-09-03T20:00:00",
        end_dt_str="2026-09-03T23:00:00",
        reference_time=ref_time
    ) is False

    # 6. Past start date with future end date (e.g. Aug 22 start, Sep 10 end) -> MUST BE PASSED
    assert RedisEventStorage.is_event_passed(
        start_dt_str="2026-08-22T11:00:00",
        end_dt_str="2026-09-10T23:59:59",
        reference_time=ref_time
    ) is True

    # 7. Past start date (Aug 15) with Sep 6 end date -> MUST BE PASSED
    assert RedisEventStorage.is_event_passed(
        start_dt_str="2026-08-15T14:00:00",
        end_dt_str="2026-09-06T19:00:00",
        reference_time=ref_time
    ) is True

    # 8. Past start date (Sep 1) with Sep 11 end date -> MUST BE PASSED
    assert RedisEventStorage.is_event_passed(
        start_dt_str="2026-09-01T08:00:00",
        end_dt_str="2026-09-11T23:59:59",
        reference_time=ref_time
    ) is True

    # 9. Unparseable dates (e.g. "Upcoming") should not be falsely dropped
    assert RedisEventStorage.is_event_passed(
        start_dt_str="Upcoming",
        end_dt_str=None,
        reference_time=ref_time
    ) is False
    print("✓ is_event_passed tests passed.")


async def test_calculate_ttl_seconds():
    print("Testing calculate_ttl_seconds...")
    # Very ancient event (> 14 days ago) should yield 0 TTL (discard)
    ancient_date = (datetime.now(EAT_TIMEZONE) - timedelta(days=20)).isoformat()
    assert RedisEventStorage.calculate_ttl_seconds(start_dt_str=ancient_date, end_dt_str=ancient_date) == 0

    # Recent past event (3 days ago) should yield positive retention TTL
    recent_past = (datetime.now(EAT_TIMEZONE) - timedelta(days=3)).isoformat()
    past_ttl = RedisEventStorage.calculate_ttl_seconds(start_dt_str=recent_past, end_dt_str=recent_past)
    assert past_ttl > 0

    # Future event should yield >= 3600 seconds
    tomorrow = (datetime.now(EAT_TIMEZONE) + timedelta(days=1)).isoformat()
    ttl = RedisEventStorage.calculate_ttl_seconds(start_dt_str=tomorrow, end_dt_str=tomorrow)
    assert ttl >= 3600
    print("✓ calculate_ttl_seconds tests passed.")


async def test_redis_upcoming_and_past_partitioning():
    print("Testing Redis upcoming vs past storage and cleanup...")
    storage = RedisEventStorage()
    try:
        client = await storage.get_client()
        await client.ping()
    except Exception as e:
        print(f"Skipping live Redis test (Redis not accessible: {e})")
        return

    past_date = (datetime.now(EAT_TIMEZONE) - timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    future_date = (datetime.now(EAT_TIMEZONE) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")

    # 1. Save past event
    saved_past = await storage.save_event(
        platform="test_platform",
        post_id="past_test_1",
        event_dict={
            "title": "Past Jazz Night",
            "start_datetime": past_date,
            "end_datetime": past_date,
        }
    )
    assert saved_past is True

    # 2. Save future event
    saved_future = await storage.save_event(
        platform="test_platform",
        post_id="future_test_1",
        event_dict={
            "title": "Future Tech Summit",
            "start_datetime": future_date,
            "end_datetime": future_date,
        }
    )
    assert saved_future is True

    # 3. Query Upcoming only -> should include future, exclude past
    upcoming_events = await storage.get_all_active_events(timeframe="upcoming")
    upcoming_titles = [e.get("event", {}).get("title") for e in upcoming_events]
    assert "Future Tech Summit" in upcoming_titles
    assert "Past Jazz Night" not in upcoming_titles

    # 4. Query Past only -> should include past, exclude future
    past_events = await storage.get_all_active_events(timeframe="past")
    past_titles = [e.get("event", {}).get("title") for e in past_events]
    assert "Past Jazz Night" in past_titles
    assert "Future Tech Summit" not in past_titles

    # 5. Clean up passed events with max_age_days=0 (cleans all passed)
    cleanup_res = await storage.cleanup_passed_events(max_age_days=0)
    assert cleanup_res["status"] == "success"
    assert cleanup_res["cleaned_count"] >= 1

    # Verify past event was deleted from Redis
    assert await storage.get_event("test_platform", "past_test_1") is None
    # Verify future event remains in Redis
    assert await storage.get_event("test_platform", "future_test_1") is not None

    # Clean up test future key
    await client.delete("event:test_platform:future_test_1")
    await storage.close()
    print("✓ Redis upcoming/past partitioning & cleanup tests passed.")


async def test_cleanup_api_endpoints():
    print("Testing API cleanup & explore endpoints...")
    test_key = "test_pipeline_secret_key_123"
    original_key = settings.PIPELINE_API_KEY
    settings.PIPELINE_API_KEY = test_key

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Scraper cleanup without header -> 422 (FastAPI missing header validation) or 403
        res_no_auth = await client.post("/api/v1/scraper/cleanup")
        assert res_no_auth.status_code in (401, 403, 422)

        # 2. Scraper cleanup with invalid key -> 403
        res_bad_key = await client.post(
            "/api/v1/scraper/cleanup",
            headers={"X-Api-Key": "wrong_key"}
        )
        assert res_bad_key.status_code == 403

        # 3. Scraper cleanup with valid key -> 200
        res_valid = await client.post(
            "/api/v1/scraper/cleanup?max_age_days=7",
            headers={"X-Api-Key": test_key}
        )
        assert res_valid.status_code == 200
        data = res_valid.json()
        assert data["status"] in ("success", "queued")
        assert "cleaned_count" in data

        # 4. Events cleanup endpoint -> 200
        res_events = await client.post(
            "/api/v1/events/cleanup?max_age_days=7",
            headers={"X-Api-Key": test_key}
        )
        assert res_events.status_code == 200

        # 5. Explore endpoint with timeframe parameter -> 200
        res_upcoming = await client.get("/api/v1/events/explore?timeframe=upcoming")
        assert res_upcoming.status_code == 200
        assert isinstance(res_upcoming.json(), list)

        res_past = await client.get("/api/v1/events/explore?timeframe=past")
        assert res_past.status_code == 200
        assert isinstance(res_past.json(), list)

        res_past_alias = await client.get("/api/v1/events/past")
        assert res_past_alias.status_code == 200
        assert isinstance(res_past_alias.json(), list)

    settings.PIPELINE_API_KEY = original_key
    print("✓ API endpoints verification passed.")


async def main():
    print("=" * 60)
    print("Running Passed Events & Cleanup Test Suite")
    print("=" * 60)
    await test_parse_iso_datetime()
    await test_is_event_passed()
    await test_calculate_ttl_seconds()
    await test_redis_upcoming_and_past_partitioning()
    await test_cleanup_api_endpoints()
    print("=" * 60)
    print("ALL TESTS PASSED SUCCESSFULLY! 🎉")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
