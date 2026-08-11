#!/usr/bin/env python3
"""Seed default interests into PostgreSQL 'interests' table."""

import asyncio
import logging
import sys
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.db.session import AsyncSessionLocal
from app.db.models import Interest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("SeedInterests")

DEFAULT_INTERESTS = [
    {"slug": "music", "name_en": "Music & Concerts", "name_am": "ሙዚቃና ኮንሰርት", "icon_name": "🎵"},
    {"slug": "nightlife", "name_en": "Nightlife & Parties", "name_am": "ምሽት ህይወትና ፓርቲ", "icon_name": "🍸"},
    {"slug": "tech", "name_en": "Tech & Software", "name_am": "ቴክኖሎጂና ሶፍትዌር", "icon_name": "💻"},
    {"slug": "business", "name_en": "Business & Entrepreneurship", "name_am": "ቢዝነስና ስራ ፈጠራ", "icon_name": "💼"},
    {"slug": "art", "name_en": "Arts, Exhibition & Culture", "name_am": "ጥበብና ባህል", "icon_name": "🎨"},
    {"slug": "food", "name_en": "Food, Coffee & Dining", "name_am": "ምግብና ቡና", "icon_name": "☕"},
    {"slug": "cinema", "name_en": "Movies, Cinema & Theater", "name_am": "ፊልምና ቴአትር", "icon_name": "🍿"},
    {"slug": "sports", "name_en": "Sports, Gaming & Esports", "name_am": "ስፖርትና ጌሚንግ", "icon_name": "⚽"},
    {"slug": "fitness", "name_en": "Fitness, Health & Wellness", "name_am": "ጤናና ፊትንስ", "icon_name": "🧘"},
    {"slug": "outdoor", "name_en": "Outdoors, Travel & Hiking", "name_am": "የቤት ውጪና ጉዞ", "icon_name": "🌲"},
    {"slug": "education", "name_en": "Education, Workshops & Training", "name_am": "ትምህርትና ስልጠና", "icon_name": "🎓"},
    {"slug": "fashion", "name_en": "Fashion, Beauty & Modeling", "name_am": "ፋሽንና ውበት", "icon_name": "👗"},
    {"slug": "bazaars", "name_en": "Bazaars, Expos & Trade Fairs", "name_am": "ባዛርና ኤግዚቢሽን", "icon_name": "🛍️"},
    {"slug": "community", "name_en": "Community, Networking & Meetups", "name_am": "ማህበረሰብና ትስስር", "icon_name": "🤝"},
    {"slug": "charity", "name_en": "Charity, Non-Profit & Social Causes", "name_am": "በጎ አድራጎት", "icon_name": "❤️"},
    {"slug": "kids", "name_en": "Kids, Family & Youth", "name_am": "ህፃናትና ቤተሰብ", "icon_name": "🧸"},
    {"slug": "realestate", "name_en": "Real Estate, Architecture & Design", "name_am": "ሪል እስቴትና ዲዛይን", "icon_name": "🏢"},
    {"slug": "science", "name_en": "Science, Innovation & Research", "name_am": "ሳይንስና ምርምር", "icon_name": "🔬"},
    {"slug": "books", "name_en": "Books, Literature & Poetry", "name_am": "መጽሐፍትና ግጥም", "icon_name": "📚"},
    {"slug": "faith", "name_en": "Religious, Spiritual & Faith", "name_am": "ሃይማኖታዊና መንፈሳዊ", "icon_name": "🕊️"},
    {"slug": "government", "name_en": "Government, Policy & Law", "name_am": "መንግስትና ህግ", "icon_name": "🏛️"},
    {"slug": "general", "name_en": "Other / General", "name_am": "ሌሎች", "icon_name": "✨"},
]


async def seed_interests():
    logger.info("Seeding default interests into PostgreSQL database...")
    async with AsyncSessionLocal() as session:
        count = 0
        for item in DEFAULT_INTERESTS:
            stmt = insert(Interest).values(
                slug=item["slug"],
                name_en=item["name_en"],
                name_am=item["name_am"],
                icon_name=item["icon_name"]
            )
            upsert_stmt = stmt.on_conflict_do_update(
                index_elements=["slug"],
                set_={
                    "name_en": item["name_en"],
                    "name_am": item["name_am"],
                    "icon_name": item["icon_name"],
                }
            )
            await session.execute(upsert_stmt)
            count += 1

        await session.commit()
async def seed_targets():
    import json
    from pathlib import Path
    from app.db.models import ScraperTargetDB, ScraperPlatformEnum, ScraperTargetType

    config_path = Path("targets_config.json")
    if not config_path.exists():
        logger.warning("targets_config.json not found, skipping target seeding.")
        return

    logger.info("Seeding scraper targets from targets_config.json into PostgreSQL...")
    with open(config_path, "r", encoding="utf-8") as f:
        targets_list = json.load(f)

    async with AsyncSessionLocal() as session:
        count = 0
        for item in targets_list:
            plat_enum = ScraperPlatformEnum(item["platform"].lower())
            ttype_enum = ScraperTargetType(item.get("target_type", "username").lower())

            stmt = insert(ScraperTargetDB).values(
                platform=plat_enum,
                target_type=ttype_enum,
                value=item["value"].strip(),
                max_posts_per_cycle=item.get("max_posts", 5),
                last_watermark=str(item.get("last_watermark", "0")),
                is_active=item.get("is_active", True)
            )
            upsert_stmt = stmt.on_conflict_do_update(
                constraint="uq_scraper_target",
                set_={
                    "max_posts_per_cycle": item.get("max_posts", 5),
                    "is_active": item.get("is_active", True),
                }
            )
            await session.execute(upsert_stmt)
            count += 1

        await session.commit()
        logger.info(f"Successfully seeded/upserted {count} scraper targets in PostgreSQL database!")


async def run_all_seeds():
    await seed_interests()
    await seed_targets()


if __name__ == "__main__":
    asyncio.run(run_all_seeds())
