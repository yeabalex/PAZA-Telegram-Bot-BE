#!/usr/bin/env python3
"""Database & Cache Status Inspector Script."""

import asyncio
from sqlalchemy import select
from app.db.session import AsyncSessionLocal
from app.db.models import ScraperTargetDB
from app.services.cache.redis_event_storage import RedisEventStorage


async def inspect_db_and_cache():
    print("=" * 80)
    print("           POSTGRESQL DATABASE & REDIS CACHE STATUS INSPECTOR")
    print("=" * 80)

    # 1. Fetch targets from PostgreSQL DB
    async with AsyncSessionLocal() as session:
        res = await session.execute(select(ScraperTargetDB).order_by(ScraperTargetDB.platform, ScraperTargetDB.value))
        db_targets = res.scalars().all()

        print(f"\n--- [PostgreSQL] Scraper Targets ({len(db_targets)} total) ---")
        processed_targets = 0
        for t in db_targets:
            watermark = str(t.last_watermark or "0")
            is_processed = "✅ Done" if watermark != "0" else "⏳ Pending/Starting"
            if watermark != "0":
                processed_targets += 1
            print(f" • [{t.platform.value.upper():<9}] @{t.value:<25} -> Watermark: {watermark:<20} ({is_processed})")

        print(f"\nTarget Summary: {processed_targets}/{len(db_targets)} targets have updated watermarks.")

    # 2. Fetch extracted events from Redis Cache
    try:
        redis_storage = RedisEventStorage()
        events = await redis_storage.get_all_active_events()
        print(f"\n--- [Redis/Valkey Cache] Extracted Active Events ({len(events)} total) ---")
        for idx, ev in enumerate(events, 1):
            event_data = ev.get("event") or ev
            title = event_data.get("title") or "Untitled Event"
            venue = event_data.get("venue_name") or "TBA"
            price = event_data.get("entrance_fee_etb") or "Free / Unspecified"
            platform = ev.get("platform") or "unknown"
            start_date = event_data.get("start_datetime") or "N/A"
            print(f" {idx:2d}. [{platform.upper():<9}] \"{title}\"")
            print(f"     Venue: {venue} | Date: {start_date} | Price: {price} ETB")
        await redis_storage.close()
    except Exception as redis_err:
        print(f"\nRedis cache note: {redis_err}")

    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(inspect_db_and_cache())
