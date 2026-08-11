"""Security and Authentication utilities module."""

import base64
import hashlib
import hmac
import json
import logging
import time
from typing import Optional
from urllib.parse import parse_qsl

from app.core.config import settings

logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """Hashes a password using PBKDF2 with SHA256."""
    salt = settings.JWT_SECRET_KEY[:16].encode("utf-8")
    key = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100000)
    return key.hex()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifies a plain password against stored hash."""
    return hmac.compare_digest(hash_password(plain_password), hashed_password)


def create_access_token(user_id: str, email: str, role: str) -> str:
    """Generates an HMAC-SHA256 signed JWT bearer token."""
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    expires = now + (settings.JWT_ACCESS_TOKEN_EXPIRE_DAYS * 86400)
    payload = {
        "sub": str(user_id),
        "email": email,
        "role": role,
        "iat": now,
        "exp": expires,
    }

    def _b64url(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")

    header_b64 = _b64url(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature_base = f"{header_b64}.{payload_b64}".encode("utf-8")
    signature = hmac.new(settings.JWT_SECRET_KEY.encode("utf-8"), signature_base, hashlib.sha256).digest()
    sig_b64 = _b64url(signature)

    return f"{header_b64}.{payload_b64}.{sig_b64}"


def decode_access_token(token: str) -> Optional[dict]:
    """Decodes and validates HMAC-SHA256 signed JWT token."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        header_b64, payload_b64, sig_b64 = parts

        signature_base = f"{header_b64}.{payload_b64}".encode("utf-8")
        expected_sig = hmac.new(settings.JWT_SECRET_KEY.encode("utf-8"), signature_base, hashlib.sha256).digest()

        def _b64decode(s: str) -> bytes:
            padding = "=" * (4 - len(s) % 4)
            return base64.urlsafe_b64decode(s + padding)

        if not hmac.compare_digest(_b64decode(sig_b64), expected_sig):
            return None

        payload_bytes = _b64decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))

        if payload.get("exp", 0) < int(time.time()):
            logger.warning("Token expired")
            return None

        return payload
    except Exception as e:
        logger.warning(f"Failed to decode token: {e}")
        return None


def verify_telegram_init_data(init_data: str, bot_token: str, max_age_seconds: int = 86400) -> Optional[dict]:
    """Verify Telegram WebApp initData HMAC-SHA256 signature with replay protection."""
    if not init_data or not bot_token:
        return None

    try:
        parsed_data = dict(parse_qsl(init_data, keep_blank_values=True))
        if "hash" not in parsed_data:
            return None

        data_hash = parsed_data.pop("hash")
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed_data.items()))

        secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

        if hmac.compare_digest(calculated_hash, data_hash):
            # Replay protection: verify auth_date freshness (default 24h)
            auth_date = int(parsed_data.get("auth_date", 0))
            if auth_date > 0 and (time.time() - auth_date > max_age_seconds):
                logger.warning(f"Telegram initData expired (auth_date={auth_date}) — rejecting replay attempt.")
                return None

            if "user" in parsed_data:
                return json.loads(parsed_data["user"])
            return parsed_data
    except Exception as e:
        logger.warning(f"Telegram initData verification error: {e}")
    return None


# ════════════════════════════════════════════════════════════════════════════════
# FastAPI Reusable Auth Dependencies
# ════════════════════════════════════════════════════════════════════════════════

from fastapi import Header, HTTPException, status


async def require_api_key(x_api_key: str = Header(..., alias="X-Api-Key")) -> str:
    """Validates the X-Api-Key header against PIPELINE_API_KEY.

    Use as a dependency on server-to-server routes (scraper trigger, cron jobs).
    Raises 403 if the key is missing, empty, or does not match.
    """
    if not settings.PIPELINE_API_KEY:
        logger.error("PIPELINE_API_KEY is not configured on the server — rejecting request.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server API key not configured.",
        )
    if not hmac.compare_digest(x_api_key, settings.PIPELINE_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API key.",
        )
    return x_api_key


async def require_telegram_user(
    x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data"),
) -> dict:
    """Validates Telegram WebApp initData from the X-Telegram-Init-Data header.

    Use as a dependency on Mini App user-action routes (RSVP, save, invite, etc.).
    Returns the verified Telegram user dict (contains 'id', 'first_name', etc.)
    or raises 401 if verification fails.
    """
    tg_user = verify_telegram_init_data(x_telegram_init_data, settings.TELEGRAM_BOT_TOKEN)
    if not tg_user or "id" not in tg_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired Telegram initData.",
        )
    return tg_user

