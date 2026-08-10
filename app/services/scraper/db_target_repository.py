"""PostgreSQL Target Repository for managing active scraper targets and watermarks."""

import logging
from typing import List
from sqlalchemy import select, update
from app.db.session import AsyncSessionLocal
from app.db.models import ScraperTargetDB, ScraperPlatformEnum, ScraperTargetType
from app.schemas.event import ScraperTarget, ScraperPlatform, TargetType

logger = logging.getLogger(__name__)


class DatabaseTargetRepository:
    """Loads scraping targets from PostgreSQL and syncs updated watermarks."""

    async def get_active_targets(self) -> List[ScraperTarget]:
        """Fetch all active targets (is_active = True) from PostgreSQL DB."""
        try:
            async with AsyncSessionLocal() as session:
                stmt = select(ScraperTargetDB).where(ScraperTargetDB.is_active == True)
                res = await session.execute(stmt)
                db_targets = res.scalars().all()

                targets = [
                    ScraperTarget(
                        platform=ScraperPlatform(t.platform.value if hasattr(t.platform, "value") else str(t.platform)),
                        target_type=TargetType(t.target_type.value if hasattr(t.target_type, "value") else str(t.target_type)),
                        value=t.value,
                        max_posts=t.max_posts_per_cycle,
                        last_watermark=str(t.last_watermark or "0"),
                        is_active=t.is_active
                    )
                    for t in db_targets
                ]
                logger.info(f"Fetched {len(targets)} active targets from PostgreSQL database.")
                return targets
        except Exception as e:
            logger.error(f"Failed to fetch active targets from PostgreSQL: {e}")
            raise RuntimeError(f"Failed to fetch active targets from PostgreSQL: {e}") from e

    async def update_watermark(self, platform: str, value: str, new_watermark: str) -> bool:
        """Update last_watermark for a target in PostgreSQL DB."""
        async with AsyncSessionLocal() as session:
            try:
                # Support both enum and string matching
                stmt = (
                    update(ScraperTargetDB)
                    .where(
                        ScraperTargetDB.value == value
                    )
                    .values(last_watermark=new_watermark)
                )
                await session.execute(stmt)
                await session.commit()
                logger.info(f"PostgreSQL: Updated watermark for [{platform}] @{value} -> {new_watermark}")
                return True
            except Exception as e:
                logger.error(f"Failed to update PostgreSQL watermark for [{platform}] @{value}: {e}")
                await session.rollback()
                raise RuntimeError(f"Failed to update PostgreSQL watermark for [{platform}] @{value}: {e}") from e

    async def sync_all_watermarks(self, updated_targets: List[ScraperTarget]) -> None:
        """Batch update watermarks for all processed targets back to PostgreSQL DB."""
        for target in updated_targets:
            if target.last_watermark:
                await self.update_watermark(
                    platform=target.platform.value,
                    value=target.value,
                    new_watermark=target.last_watermark
                )
