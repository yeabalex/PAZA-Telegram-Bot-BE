#!/usr/bin/env python3
"""Standalone Cron Executable Script to run the Multi-Platform Scraping Pipeline."""

import asyncio
import logging
import sys
from app.services.pipeline_gateway import run_pipeline_gateway

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)


def main():
    summary = asyncio.run(run_pipeline_gateway())
    print("\n--- Pipeline Gateway Result ---")
    print(summary)


if __name__ == "__main__":
    main()
