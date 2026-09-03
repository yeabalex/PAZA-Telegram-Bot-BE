"""Scraper & Pipeline Trigger Endpoint."""

import logging
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.security import require_api_key
from app.services.pipeline_gateway import run_pipeline_gateway
from app.services.cache.redis_event_storage import RedisEventStorage

logger = logging.getLogger(__name__)
router = APIRouter()


class TriggerResponse(BaseModel):
    message: str
    status: str
    mode: str


class CleanupResponse(BaseModel):
    message: str
    status: str
    mode: str
    scanned_count: Optional[int] = None
    cleaned_count: Optional[int] = None
    remaining_count: Optional[int] = None
    cleaned_events: Optional[List[Dict[str, Any]]] = None


async def background_pipeline_runner():
    """Background execution wrapper for pipeline gateway."""
    try:
        summary = await run_pipeline_gateway()
        logger.info(f"Background Cron Pipeline Run Summary: {summary}")
    except Exception as e:
        logger.error(f"Background Pipeline Run Error: {e}")


async def background_cleanup_runner(max_age_days: int = 7):
    """Background execution wrapper for Redis passed event cleanup."""
    try:
        redis_storage = RedisEventStorage()
        summary = await redis_storage.cleanup_passed_events(max_age_days=max_age_days)
        await redis_storage.close()
        logger.info(f"Background Redis Passed Event Cleanup Summary: {summary}")
    except Exception as e:
        logger.error(f"Background Redis Event Cleanup Error: {e}")


@router.post(
    "/trigger",
    response_model=TriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger Scraper Pipeline (Cron Gateway Endpoint)",
    description="Endpoint for Cron jobs or webhooks to trigger the multi-platform scraping & event extraction pipeline. Requires X-Api-Key header.",
    dependencies=[Depends(require_api_key)],
)
async def trigger_scraper_pipeline(
    background_tasks: BackgroundTasks,
    async_mode: bool = Query(True, description="If True, runs pipeline asynchronously in background"),
):
    """Gateway endpoint called by Cron jobs or external webhooks to start pipeline execution."""
    logger.info("Pipeline trigger received via API endpoint (authenticated).")

    if async_mode:
        background_tasks.add_task(background_pipeline_runner)
        return TriggerResponse(
            message="Scraper pipeline execution triggered in background successfully.",
            status="queued",
            mode="async"
        )

    # Synchronous execution mode
    try:
        summary = await run_pipeline_gateway()
        return TriggerResponse(
            message=f"Scraper pipeline execution completed in {summary.get('duration_seconds')}s. Scraped {summary.get('total_posts_scraped')} posts, extracted {summary.get('events_extracted')} events.",
            status="success",
            mode="sync"
        )
    except Exception as e:
        logger.error(f"Synchronous pipeline execution error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline execution failed: {str(e)}"
        )


@router.post(
    "/cleanup",
    response_model=CleanupResponse,
    status_code=status.HTTP_200_OK,
    summary="Trigger Passed Events Cleanup (Cron Gateway Endpoint)",
    description="Endpoint for Cron jobs or webhooks to remove passed events from Redis cache. Requires X-Api-Key header.",
    dependencies=[Depends(require_api_key)],
)
async def trigger_passed_events_cleanup(
    background_tasks: BackgroundTasks,
    async_mode: bool = Query(False, description="If True, runs cleanup asynchronously in background"),
    max_age_days: int = Query(7, description="Delete passed events older than this many days (0 deletes all passed events)"),
):
    """Gateway endpoint called by Cron jobs or webhooks to clean up concluded events from Redis."""
    logger.info(f"Passed events cleanup trigger received via API endpoint (max_age_days={max_age_days}).")

    if async_mode:
        background_tasks.add_task(background_cleanup_runner, max_age_days=max_age_days)
        return CleanupResponse(
            message="Redis passed events cleanup triggered in background successfully.",
            status="queued",
            mode="async"
        )

    try:
        redis_storage = RedisEventStorage()
        summary = await redis_storage.cleanup_passed_events(max_age_days=max_age_days)
        await redis_storage.close()
        return CleanupResponse(
            message=f"Cleaned up {summary.get('cleaned_count', 0)} passed events (older than {max_age_days}d). {summary.get('remaining_count', 0)} active events remain.",
            status="success",
            mode="sync",
            scanned_count=summary.get("scanned_count"),
            cleaned_count=summary.get("cleaned_count"),
            remaining_count=summary.get("remaining_count"),
            cleaned_events=summary.get("cleaned_events")
        )
    except Exception as e:
        logger.error(f"Synchronous event cleanup execution error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Event cleanup failed: {str(e)}"
        )
