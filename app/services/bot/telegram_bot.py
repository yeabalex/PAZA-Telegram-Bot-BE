"""Telegram Bot Registration & Mini App Gateway Handler (Python Telegram Bot)."""

import logging
from telegram import (
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.user.user_repository import UserRepository


logger = logging.getLogger("PazaEventsBot")

from telegram import MenuButtonWebApp

async def post_init(application):
    """Update Telegram chat menu button dynamically on bot startup."""
    try:
        mini_app_url = settings.MINI_APP_URL
        menu_button = MenuButtonWebApp(
            text="Launch App",
            web_app=WebAppInfo(url=mini_app_url)
        )
        await application.bot.set_chat_menu_button(menu_button=menu_button)
        logger.info(f"Successfully updated Telegram Bot Chat Menu Button to: {mini_app_url}")
    except Exception as e:
        logger.error(f"Failed to update chat menu button: {e}")


async def start_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for Telegram /start command."""
    user_tg = update.effective_user
    if not user_tg:
        return

    logger.info(f"Telegram /start received from user [{user_tg.id}] @{user_tg.username}")
    full_name = f"{user_tg.first_name or ''} {user_tg.last_name or ''}".strip()
    username = user_tg.username or None
    mini_app_url = settings.MINI_APP_URL

    async with AsyncSessionLocal() as session:
        user = await UserRepository.get_or_create_user(
            db=session,
            telegram_id=user_tg.id,
            full_name=full_name,
            username=username
        )

        # Check if phone number is already registered
        if user.phone_number:
            welcome_text = (
                f"👋 **Welcome back, {user_tg.first_name}!**\n\n"
                f"🎉 You are fully registered on **PAZA Events Bot**!\n"
                f"Discover trending concerts, nightlife, food festivals, and sports events in Addis Ababa."
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🚀 Launch Mini App", web_app=WebAppInfo(url=f"{mini_app_url}?tg_id={user_tg.id}"))]
            ])
            await update.message.reply_text(
                welcome_text,
                reply_markup=keyboard,
                parse_mode="Markdown"
            )
            return

    # If phone number is missing, prompt to share contact button
    contact_button = KeyboardButton(text="📱 Share Phone Number", request_contact=True)
    reply_keyboard = ReplyKeyboardMarkup([[contact_button]], resize_keyboard=True, one_time_keyboard=True)

    prompt_text = (
        f"👋 **Welcome to PAZA Events Bot, {user_tg.first_name}!**\n\n"
        f"To complete registration and get personalized event recommendations in Addis Ababa, "
        f"please share your phone number using the button below:"
    )
    await update.message.reply_text(prompt_text, reply_markup=reply_keyboard, parse_mode="Markdown")

    # Send inline button for immediate Mini App access
    inline_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Launch Mini App", web_app=WebAppInfo(url=f"{mini_app_url}?tg_id={user_tg.id}"))]
    ])
    await update.message.reply_text(
        "Or tap below to open PAZA Events Mini App:",
        reply_markup=inline_keyboard
    )


async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler for user contact button share."""
    contact = update.message.contact
    user_tg = update.effective_user

    if not contact or not user_tg:
        return

    phone_number = contact.phone_number
    logger.info(f"Received contact share from user [{user_tg.id}]: {phone_number}")
    mini_app_url = settings.MINI_APP_URL

    async with AsyncSessionLocal() as session:
        await UserRepository.update_phone_number(session, user_tg.id, phone_number)

    success_text = (
        f"✅ **Registration Complete!**\n\n"
        f"Thank you for sharing your phone number (`{phone_number}`).\n\n"
        f"Tap **Start Mini App** below to select your event interests and explore upcoming events in Addis Ababa! 🎟️"
    )

    inline_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Start Mini App", web_app=WebAppInfo(url=f"{mini_app_url}?tg_id={user_tg.id}"))]
    ])

    await update.message.reply_text(
        success_text,
        reply_markup=inline_keyboard,
        parse_mode="Markdown"
    )


import os
from telegram.request import HTTPXRequest

def build_telegram_bot_app():
    """Build Python Telegram Bot Application with robust network timeouts and optional proxy."""
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY") or getattr(settings, "TELEGRAM_PROXY_URL", None)
    request = HTTPXRequest(
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
        proxy=proxy_url if proxy_url else None,
    )
    app = (
        ApplicationBuilder()
        .token(settings.TELEGRAM_BOT_TOKEN)
        .request(request)
        .get_updates_request(request)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start", start_command_handler))
    app.add_handler(MessageHandler(filters.CONTACT, contact_handler))
    return app
