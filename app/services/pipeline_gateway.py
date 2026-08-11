"""Pipeline Gateway Module — Central execution gateway for triggering multi-platform scraping & event extraction pipeline.

Can be called directly as a Python library function, executed via CLI, or triggered asynchronously via FastAPI endpoint / Cron job.
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Dict, Any, List

from app.core.pipeline_logger import PipelineLogger
from app.schemas.event import ScraperTarget
from app.services.scraper.db_target_repository import DatabaseTargetRepository
from app.services.cache.redis_event_storage import RedisEventStorage
from app.services.scraper.redis_queue import RedisQueueManager
from app.services.scraper.producer import ScraperProducer
from app.services.transcriber.whisper import WhisperTranscriber
from app.services.classifier.event_classifier import EventClassifier
from app.services.llm.router import LLMRouter


async def run_pipeline_gateway(
    config_file: str = "targets_config.json",
    output_file: str = "scraped_events_output.json"
) -> Dict[str, Any]:
    """Central Gateway Function to trigger full multi-platform scraping pipeline.
    
    1. Fetch active targets from PostgreSQL DB (with fallback to config file)
    2. Execute unified scraping cycle across Telegram, Instagram, TikTok
    3. Update watermarks back to DB & config file
    4. Run video audio transcriptions (Whisper) & local Event Classification
    5. Pass event candidates to LLM Router for structured event extraction
    6. Save events to Redis/Valkey cache & produce JSON execution summary
    """
    start_time = PipelineLogger.log_pipeline_start(config_file, output_file)

    db_repo = DatabaseTargetRepository()
    redis_storage = RedisEventStorage()

    # Stage 1: Fetch active targets from PostgreSQL DB
    PipelineLogger.log_stage(1, "PostgreSQL Active Targets Fetch")
    try:
        targets = await db_repo.get_active_targets()
    except Exception as db_err:
        PipelineLogger.log_pipeline_failure("Stage 1: PostgreSQL Active Targets Fetch", db_err, time.time() - start_time)
        raise RuntimeError(f"Pipeline Gateway failed fetching active targets from PostgreSQL: {db_err}") from db_err

    if not targets:
        path = Path(config_file)
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                raw_list = json.load(f)
            targets = [
                ScraperTarget(
                    platform=item["platform"],
                    target_type=item.get("target_type", "username"),
                    value=item["value"].strip(),
                    max_posts=item.get("max_posts", 5),
                    last_watermark=str(item.get("last_watermark", "0")),
                    is_active=item.get("is_active", True)
                )
                for item in raw_list
            ]
            PipelineLogger.log_stage(1, "PostgreSQL Active Targets Fetch", f"Loaded {len(targets)} fallback targets from '{config_file}'")
        else:
            err = RuntimeError(f"No active targets found in PostgreSQL DB or '{config_file}'")
            PipelineLogger.log_pipeline_failure("Stage 1: Target Load", err, time.time() - start_time)
            raise err

    # Stage 2: Run scraping producer cycle
    PipelineLogger.log_stage(2, "Multi-Platform Scraping Producer Cycle", f"{len(targets)} active targets")
    queue_manager = RedisQueueManager()
    producer = ScraperProducer(queue_manager=queue_manager)

    try:
        updated_targets = await producer.run_unified_producer_cycle(targets)
    except Exception as scrap_err:
        PipelineLogger.log_pipeline_failure("Stage 2: Multi-Platform Scraping Producer Cycle", scrap_err, time.time() - start_time)
        raise RuntimeError(f"Pipeline Gateway scraping producer cycle failed: {scrap_err}") from scrap_err

    # Stage 3: Sync watermarks back to DB
    PipelineLogger.log_stage(3, "PostgreSQL Watermark Synchronization")
    try:
        await db_repo.sync_all_watermarks(updated_targets)
    except Exception as db_sync_err:
        PipelineLogger.log_pipeline_failure("Stage 3: PostgreSQL Watermark Synchronization", db_sync_err, time.time() - start_time)
        raise RuntimeError(f"Pipeline Gateway failed syncing watermarks to PostgreSQL: {db_sync_err}") from db_sync_err

    # Stage 4 & 5: Processing staged raw posts & LLM extraction
    staged_task_ids = list(queue_manager._in_memory_staging.keys())
    PipelineLogger.log_stage(4, "Post Processing & LLM Extraction", f"Processing {len(staged_task_ids)} staged posts")

    transcriber = WhisperTranscriber()
    classifier = EventClassifier.get_instance()
    llm_router = LLMRouter()

    scraped_posts: List[Dict[str, Any]] = []
    events_extracted_count = 0
    non_events_count = 0
    failed_transcriptions_count = 0
    failed_extractions_count = 0

    for task_id in staged_task_ids:
        staged = await queue_manager.get_staged_message(task_id)
        if not staged:
            continue

        raw_caption = staged.get("raw_text") or ""
        post_url = staged.get("post_url") or ""
        platform = staged.get("platform")

        # Transcribe audio for video posts if needed
        if platform in ("tiktok", "instagram") and post_url:
            try:
                raw_caption = await transcriber.transcribe_post_video_if_needed(
                    post_url=post_url,
                    current_caption=raw_caption,
                    min_caption_len=150
                )
            except Exception as t_err:
                failed_transcriptions_count += 1

        # Local Classifier
        is_event, confidence, meta = classifier.classify(raw_caption)
        extracted_event_data = None
        extracted_by_provider = None

        if is_event:
            llm_context = f"[Platform: {platform} | Source: @{staged.get('channel_username')}]\n\n{raw_caption}"
            try:
                event_res, provider_name = await llm_router.extract_event_alternating(llm_context)
                await asyncio.sleep(2.0)  # Rate-limit pacing
                extracted_by_provider = provider_name

                if event_res and event_res.is_event:
                    events_extracted_count += 1
                    extracted_event_data = {
                        "title": event_res.title,
                        "description": event_res.description,
                        "short_summary": event_res.short_summary,
                        "start_datetime": event_res.start_datetime,
                        "end_datetime": event_res.end_datetime,
                        "venue_name": event_res.venue_name,
                        "location_gps": event_res.location_gps,
                        "sub_city": event_res.sub_city,
                        "entrance_fee_etb": event_res.entrance_fee_etb,
                        "category": event_res.category,
                        "confidence_score": event_res.confidence_score,
                    }
                    post_id = staged.get("message_id") or task_id
                    try:
                        await redis_storage.save_event(
                            platform=platform,
                            post_id=str(post_id),
                            event_dict=extracted_event_data,
                            raw_metadata={
                                "task_id": task_id,
                                "handle_or_channel": staged.get("channel_username"),
                                "post_url": post_url,
                                "extracted_by": provider_name,
                                "classifier_score": confidence
                            }
                        )
                    except Exception as redis_save_err:
                        PipelineLogger.log_pipeline_failure("Stage 6: Redis Cache Storage", redis_save_err, time.time() - start_time)
                        raise redis_save_err
                else:
                    non_events_count += 1
            except Exception as llm_err:
                failed_extractions_count += 1
        else:
            non_events_count += 1

        scraped_posts.append({
            "task_id": task_id,
            "platform": platform,
            "handle_or_channel": staged.get("channel_username"),
            "post_id": staged.get("message_id"),
            "post_url": post_url,
            "scraped_date": staged.get("scraped_date"),
            "is_event_candidate": is_event,
            "classifier_score": confidence,
            "extracted_by": extracted_by_provider,
            "extracted_event": extracted_event_data,
            "raw_caption": raw_caption
        })

    await redis_storage.close()

    # Stage 6: Write audit output file
    PipelineLogger.log_stage(6, "Audit Report Export", f"Writing JSON output to '{output_file}'")
    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(scraped_posts, f, indent=2, ensure_ascii=False)
    except Exception as file_err:
        PipelineLogger.log_pipeline_failure("Stage 6: Audit Report Export", file_err, time.time() - start_time)
        raise file_err

    duration = round(time.time() - start_time, 2)
    summary = PipelineLogger.log_pipeline_success(
        duration_seconds=duration,
        targets_processed=len(targets),
        total_posts_scraped=len(scraped_posts),
        events_extracted=events_extracted_count,
        non_events_count=non_events_count,
        failed_transcriptions=failed_transcriptions_count,
        failed_extractions=failed_extractions_count,
        output_file=output_file
    )

    # Dispatch summary & JSON report to Telegram Admin Chat and delete temporary file
    await send_pipeline_telegram_report(summary, output_file)

    return summary


async def send_pipeline_telegram_report(summary: Dict[str, Any], output_file: str):
    """Sends pipeline log summary & JSON export document to Admin Telegram Chat ID, then deletes local file."""
    import os
    import httpx
    from app.core.config import settings

    bot_token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.ADMIN_TELEGRAM_CHAT_ID

    if not bot_token or not chat_id:
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
            except Exception:
                pass
        return

    caption = (
        f"📊 <b>Paza Pipeline Run Summary</b>\n\n"
        f"⏱️ <b>Duration:</b> <code>{summary.get('duration_seconds', 0)}s</code>\n"
        f"🎯 <b>Targets Processed:</b> {summary.get('targets_processed', 0)}\n"
        f"📥 <b>Total Posts Scraped:</b> {summary.get('total_posts_scraped', 0)}\n"
        f"✨ <b>Events Extracted:</b> {summary.get('events_extracted', 0)}\n"
        f"❌ <b>Non-Events Filtered:</b> {summary.get('non_events_count', 0)}\n"
        f"⚠️ <b>Failed Extractions:</b> {summary.get('failed_extractions', 0)}\n"
        f"🎙️ <b>Failed Transcriptions:</b> {summary.get('failed_transcriptions', 0)}\n\n"
        f"🧹 <i>Temporary log file sent and purged from server.</i>"
    )

    api_url = f"https://api.telegram.org/bot{bot_token}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
                with open(output_file, "rb") as f:
                    doc_url = f"{api_url}/sendDocument"
                    files = {"document": (os.path.basename(output_file), f, "application/json")}
                    data = {
                        "chat_id": chat_id,
                        "caption": caption,
                        "parse_mode": "HTML"
                    }
                    await client.post(doc_url, data=data, files=files)
            else:
                msg_url = f"{api_url}/sendMessage"
                await client.post(msg_url, json={
                    "chat_id": chat_id,
                    "text": caption,
                    "parse_mode": "HTML"
                })
    except Exception as err:
        PipelineLogger.log_pipeline_failure("Telegram Log Dispatcher", err, 0)
    finally:
        if os.path.exists(output_file):
            try:
                os.remove(output_file)
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(run_pipeline_gateway())
