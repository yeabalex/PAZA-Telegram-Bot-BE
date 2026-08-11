"""Scraper & Pipeline Trigger Endpoint."""

import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.security import require_api_key
from app.services.pipeline_gateway import run_pipeline_gateway

logger = logging.getLogger(__name__)
router = APIRouter()


class TriggerResponse(BaseModel):
    message: str
    status: str
    mode: str


async def background_pipeline_runner():
    """Background execution wrapper for pipeline gateway."""
    try:
        summary = await run_pipeline_gateway()
        logger.info(f"Background Cron Pipeline Run Summary: {summary}")
    except Exception as e:
        logger.error(f"Background Pipeline Run Error: {e}")


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

