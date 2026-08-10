"""Pipeline Logger Module using Loguru and Rich for structured logging and execution metrics reporting."""

import sys
import time
from typing import Dict, Any, Optional
from loguru import logger
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()

from pathlib import Path

# Ensure logs directory exists
Path("logs").mkdir(exist_ok=True)

# Configure Loguru format for pipeline logger
logger.remove()
logger.add(
    sys.stderr,
    format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level:<8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
    level="INFO",
    colorize=True
)
logger.add(
    "logs/pipeline.log",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {name}:{line} - {message}",
    level="INFO",
    rotation="10 MB",
    retention="7 days",
    encoding="utf-8"
)

class PipelineLogger:
    """Structured Pipeline Logger & Metrics Visualizer using Loguru and Rich."""

    @staticmethod
    def log_pipeline_start(config_file: str, output_file: str) -> float:
        """Log pipeline initiation banner."""
        start_time = time.time()
        logger.info("================================================================================")
        logger.info("🚀 PIPELINE GATEWAY: STARTING MULTI-PLATFORM SCRAPING & EXTRACTION CYCLE")
        logger.info(f"   Config File: '{config_file}' | Audit Output File: '{output_file}'")
        logger.info("================================================================================")
        return start_time

    @staticmethod
    def log_stage(stage_number: int, stage_name: str, details: str = "") -> None:
        """Log pipeline stage execution."""
        msg = f"[Stage {stage_number}/6] {stage_name}"
        if details:
            msg += f" — {details}"
        logger.info(msg)

    @staticmethod
    def log_pipeline_success(
        duration_seconds: float,
        targets_processed: int,
        total_posts_scraped: int,
        events_extracted: int,
        non_events_count: int,
        failed_transcriptions: int,
        failed_extractions: int,
        output_file: str
    ) -> Dict[str, Any]:
        """Log rich success summary table and return summary dictionary."""
        logger.success(
            f"🎉 PIPELINE GATEWAY COMPLETED SUCCESSFULLY in {duration_seconds:.2f}s! "
            f"Scraped {total_posts_scraped} posts, extracted {events_extracted} events."
        )

        table = Table(title="📊 Pipeline Execution Metrics Summary", border_style="green")
        table.add_column("Metric", style="cyan", no_wrap=True)
        table.add_column("Value", style="bold white")
        table.add_column("Status / Detail", style="dim")

        table.add_row("Execution Status", "✅ SUCCESS", "All stages completed cleanly")
        table.add_row("Duration", f"{duration_seconds:.2f}s", "Total execution wall time")
        table.add_row("Active Targets Processed", str(targets_processed), "PostgreSQL DB / Config targets")
        table.add_row("Total Scraped Posts", str(total_posts_scraped), "Posts gathered across platforms")
        table.add_row("Successfully Extracted Events", str(events_extracted), f"Stored in Redis cache with TTL")
        table.add_row("Filtered Non-Event Posts", str(non_events_count), "Classified as non-events")
        table.add_row("Failed Transcriptions", str(failed_transcriptions), "Audio Whisper errors" if failed_transcriptions > 0 else "None")
        table.add_row("Failed LLM Extractions", str(failed_extractions), "LLM Router errors" if failed_extractions > 0 else "None")
        table.add_row("Audit File Written", output_file, "JSON execution summary")

        console.print(table)

        return {
            "status": "success",
            "duration_seconds": duration_seconds,
            "targets_processed": targets_processed,
            "total_posts_scraped": total_posts_scraped,
            "events_extracted": events_extracted,
            "non_events_count": non_events_count,
            "failed_transcriptions": failed_transcriptions,
            "failed_extractions": failed_extractions,
            "output_file": output_file,
        }

    @staticmethod
    def log_pipeline_failure(
        stage_name: str,
        error: Exception,
        duration_seconds: Optional[float] = None
    ) -> None:
        """Log structured error banner & traceback details when pipeline fails."""
        duration_str = f" after {duration_seconds:.2f}s" if duration_seconds else ""
        logger.error(f"❌ PIPELINE GATEWAY FAILED at stage '{stage_name}'{duration_str}: {error}")
        logger.exception(error)

        panel_content = Text()
        panel_content.append(f"Stage Failed: ", style="bold red")
        panel_content.append(f"{stage_name}\n", style="yellow")
        panel_content.append(f"Error Type:   ", style="bold red")
        panel_content.append(f"{type(error).__name__}\n", style="white")
        panel_content.append(f"Failure Reason:\n", style="bold red")
        panel_content.append(f"{str(error)}", style="bold white")

        console.print(Panel(panel_content, title="🚨 Pipeline Execution Failure Report", border_style="red"))
