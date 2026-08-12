"""Telegram Bot Registration & Mini App Gateway Handler (Python Telegram Bot)."""

import os
import logging
from telegram import (
    Update,
    KeyboardButton,
    ReplyKeyboardMarkup,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
    MenuButtonWebApp,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ChatMemberHandler,
    filters,
    ContextTypes,
)
from telegram.request import HTTPXRequest

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.services.user.user_repository import UserRepository
from app.services.bot.admin_notifier import notify_admin


logger = logging.getLogger("PazaEventsBot")


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
        # Check if user already exists in DB before get_or_create
        existing_user = await UserRepository.get_by_telegram_id(session, user_tg.id)
        is_new_user = existing_user is None

        user = await UserRepository.get_or_create_user(
            db=session,
            telegram_id=user_tg.id,
            full_name=full_name,
            username=username
        )
        total_users = await UserRepository.get_total_users_count(session)

    # Notify admin on new user start or first-time registration
    if is_new_user:
        user_link = f"tg://user?id={user_tg.id}"
        uname_str = f"@{username}" if username else "None"
        admin_msg = (
            f"✨ **New User Started Bot!**\n\n"
            f"👤 **Name**: {full_name or 'Anonymous'}\n"
            f"🏷️ **Username**: {uname_str}\n"
            f"🆔 **Telegram ID**: `{user_tg.id}`\n"
            f"🔗 **Profile Link**: [{full_name or 'User Profile'}]({user_link})\n\n"
            f"📊 **Total Registered Users**: `{total_users}`"
        )
        await notify_admin(admin_msg)

    organizer_portal_url = getattr(settings, "ORGANIZER_PORTAL_URL", "https://paza-organizers.netlify.app")

    welcome_text = f"👋 **Welcome to PAZA Events Bot, {user_tg.first_name}!** 🎟️"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Launch Mini App", web_app=WebAppInfo(url=f"{mini_app_url}?tg_id={user_tg.id}"))],
        [InlineKeyboardButton("🎪 Organizer Portal", url=organizer_portal_url)]
    ])
    await update.message.reply_text(
        welcome_text,
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Optional handler for user contact button share."""
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
        f"✅ **Phone Number Received!**\n\n"
        f"Thank you for sharing your contact (`{phone_number}`).\n\n"
        f"Tap **Start Mini App** below to explore upcoming events in Addis Ababa! 🎟️"
    )

    inline_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 Start Mini App", web_app=WebAppInfo(url=f"{mini_app_url}?tg_id={user_tg.id}"))]
    ])

    await update.message.reply_text(
        success_text,
        reply_markup=inline_keyboard,
        parse_mode="Markdown"
    )


async def chat_member_updated_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Track when a user blocks/stops or unblocks the bot."""
    chat_member_update = update.my_chat_member
    if not chat_member_update:
        return

    user_tg = chat_member_update.from_user
    if not user_tg:
        return

    new_status = chat_member_update.new_chat_member.status
    full_name = f"{user_tg.first_name or ''} {user_tg.last_name or ''}".strip() or "User"
    username = f"@{user_tg.username}" if user_tg.username else "None"

    async with AsyncSessionLocal() as session:
        total_users = await UserRepository.get_total_users_count(session)

    if new_status in ("kicked", "left"):
        admin_msg = (
            f"🚫 **User Stopped / Blocked Bot**\n\n"
            f"👤 **Name**: {full_name}\n"
            f"🏷️ **Username**: {username}\n"
            f"🆔 **Telegram ID**: `{user_tg.id}`\n\n"
            f"📊 **Total Registered Users**: `{total_users}`"
        )
        await notify_admin(admin_msg)
    elif new_status in ("member", "administrator"):
        admin_msg = (
            f"🟢 **User Unblocked / Reactivated Bot**\n\n"
            f"👤 **Name**: {full_name}\n"
            f"🏷️ **Username**: {username}\n"
            f"🆔 **Telegram ID**: `{user_tg.id}`\n\n"
            f"📊 **Total Registered Users**: `{total_users}`"
        )
        await notify_admin(admin_msg)


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
    app.add_handler(ChatMemberHandler(chat_member_updated_handler, ChatMemberHandler.MY_CHAT_MEMBER))
    return app
