#!/usr/bin/env python3
"""Runner Script for PAZA Events Telegram Bot (@paza_events_bot)."""

import logging
import sys
from app.services.bot.telegram_bot import build_telegram_bot_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("RunBot")


def main():
    print("=" * 80)
    print("           PAZA EVENTS TELEGRAM BOT (@paza_events_bot) POLLING ENGINE")
    print("=" * 80)
    logger.info("Initializing Telegram Bot application...")

    bot_app = build_telegram_bot_app()
    logger.info("Bot poller starting... Listening for /start and contact shares...")

    bot_app.run_polling(bootstrap_retries=-1, timeout=30)


if __name__ == "__main__":
    main()
