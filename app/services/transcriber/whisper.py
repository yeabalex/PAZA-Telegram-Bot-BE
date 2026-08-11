"""Audio Transcription Service powered by Groq Whisper API (Amharic & English support)."""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

GROQ_WHISPER_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


class WhisperTranscriber:
    """Transcribes video audio (IG Reels & TikTok) to text via Groq's free Whisper API."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or settings.GROQ_API_KEY

    def download_audio_from_url(self, post_url: str) -> Optional[str]:
        """Use yt-dlp to extract a lightweight audio file (.mp3) from a video post URL."""
        if not post_url:
            return None

        try:
            import yt_dlp

            temp_dir = tempfile.gettempdir()
            output_template = os.path.join(temp_dir, "audio_%(id)s.%(ext)s")

            from app.services.scraper.anti_block import get_random_headers
            random_headers = get_random_headers()
            http_headers = {"User-Agent": random_headers["User-Agent"]}
            if "tiktok" in post_url.lower() and settings.TIKTOK_SESSION_ID:
                http_headers["Cookie"] = f"sessionid={settings.TIKTOK_SESSION_ID}; sessionid_ss={settings.TIKTOK_SESSION_ID}"
            elif "instagram" in post_url.lower() and settings.INSTAGRAM_SESSION_ID:
                http_headers["Cookie"] = f"sessionid={settings.INSTAGRAM_SESSION_ID}"

            class YDLNullLogger:
                def debug(self, msg): pass
                def info(self, msg): pass
                def warning(self, msg): pass
                def error(self, msg): pass

            ydl_opts = {
                "format": "bestaudio/best",
                "outtmpl": output_template,
                "http_headers": http_headers,
                "logger": YDLNullLogger(),
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "128",
                }],
                "quiet": True,
                "no_warnings": True,
                "max_filesize": 10 * 1024 * 1024,  # Max 10MB audio safety cap
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(post_url, download=True)
                if not info:
                    return None

                video_id = info.get("id")
                audio_path = os.path.join(temp_dir, f"audio_{video_id}.mp3")

                if os.path.exists(audio_path):
                    return audio_path

                # Fallback check for any matching file
                for f in Path(temp_dir).glob(f"audio_{video_id}.*"):
                    return str(f)

        except Exception as e:
            logger.warning(f"yt-dlp audio download failed for {post_url}: {e}")

        # ── Fallback for TikTok audio via direct API (tikwm) ──
        if "tiktok" in post_url.lower():
            try:
                temp_dir = tempfile.gettempdir()
                import hashlib
                url_hash = hashlib.md5(post_url.encode()).hexdigest()[:8]
                fallback_audio_path = os.path.join(temp_dir, f"audio_tt_{url_hash}.mp3")

                with httpx.Client(timeout=15.0, follow_redirects=True) as client:
                    api_res = client.post("https://tikwm.com/api/", data={"url": post_url})
                    if api_res.status_code == 200:
                        tt_data = api_res.json().get("data", {})
                        media_url = tt_data.get("play") or tt_data.get("music")
                        if media_url:
                            m_res = client.get(media_url)
                            if m_res.status_code == 200 and len(m_res.content) > 1000:
                                with open(fallback_audio_path, "wb") as f:
                                    f.write(m_res.content)
            except Exception as fb_err:
                logger.debug(f"TikTok audio fallback error for {post_url}: {fb_err}")

        # ── Fallback for Instagram Reel video via session-authenticated feed ──
        if "instagram.com" in post_url.lower() and settings.INSTAGRAM_SESSION_ID:
            try:
                temp_dir = tempfile.gettempdir()
                import hashlib
                url_hash = hashlib.md5(post_url.encode()).hexdigest()[:8]
                ig_fallback_path = os.path.join(temp_dir, f"audio_ig_{url_hash}.mp4")

                # Extract reel shortcode (e.g. DbnaHKwofp0)
                reel_match = re.search(r'/(?:reel|p)/([A-Za-z0-9_-]+)', post_url)
                if reel_match:
                    shortcode = reel_match.group(1)
                    # Search recent user feed via authenticated endpoint
                    # Uses current sessionid header
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                        "Cookie": f"sessionid={settings.INSTAGRAM_SESSION_ID}",
                        "X-IG-App-ID": "936619743392459"
                    }
                    with httpx.Client(timeout=15.0, headers=headers, follow_redirects=True) as client:
                        # Try web info endpoint for shortcode
                        info_res = client.get(f"https://www.instagram.com/p/{shortcode}/?__a=1&__d=dis")
                        video_url = None
                        if info_res.status_code == 200:
                            items = info_res.json().get("items", [])
                            if items and items[0].get("video_versions"):
                                video_url = items[0]["video_versions"][0]["url"]

                        if video_url:
                            v_res = client.get(video_url)
                            if v_res.status_code == 200 and len(v_res.content) > 1000:
                                with open(ig_fallback_path, "wb") as f:
                                    f.write(v_res.content)
                                logger.info(f"Instagram Reel fallback download success ({len(v_res.content)} bytes)")
                                return ig_fallback_path
            except Exception as ig_err:
                logger.debug(f"Instagram Reel fallback note for {post_url}: {ig_err}")

        return None

    async def transcribe_audio_file_with_gemini(self, audio_filepath: str) -> Optional[str]:
        """Send audio file to Google Gemini Flash Multimodal API for high-accuracy Amharic speech-to-text."""
        if not settings.GEMINI_API_KEY:
            return None

        try:
            import base64
            with open(audio_filepath, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode("utf-8")

            mime_type = "video/mp4" if audio_filepath.lower().endswith(".mp4") else "audio/mp3"
            models_to_try = ["gemini-3.1-flash-lite", "gemini-flash-lite-latest", "gemini-2.0-flash-lite", "gemini-2.5-flash"]
            for model_id in models_to_try:
                gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent?key={settings.GEMINI_API_KEY}"
                payload = {
                    "contents": [{
                        "parts": [
                            {"inline_data": {"mime_type": mime_type, "data": audio_b64}},
                            {"text": "You are an expert Amharic and English speech-to-text transcriber. Listen carefully to the spoken voiceover in this audio/video track and write out every spoken word verbatim in Ethiopic script (አማርኛ ፊደል) for Amharic or English script for English speech. Return only the raw verbatim transcript without conversational introduction."}
                        ]
                    }]
                }

                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post(gemini_url, json=payload)
                    if resp.status_code == 200:
                        candidates = resp.json().get("candidates", [])
                        if candidates:
                            txt = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "").strip()
                            if txt:
                                logger.info(f"Gemini Audio Transcription SUCCESS via [{model_id}] ({len(txt)} chars): '{txt[:60]}...'")
                                return txt
                    elif resp.status_code == 429:
                        logger.info(f"Gemini model [{model_id}] hit 429 rate limit. Trying next model endpoint...")
                        await asyncio.sleep(2.0)
                    else:
                        logger.warning(f"Gemini Audio [{model_id}] HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            logger.warning(f"Gemini Audio transcription note: {e}")
        return None

    async def transcribe_audio_file(self, audio_filepath: str) -> Optional[str]:
        """Transcribe audio file using Gemini Flash Audio API (primary) or Groq Whisper (fallback)."""
        if not os.path.exists(audio_filepath):
            return None

        # ── Primary: Google Gemini Multimodal Audio API for Amharic ──
        if settings.GEMINI_API_KEY:
            gemini_transcript = await self.transcribe_audio_file_with_gemini(audio_filepath)
            if gemini_transcript:
                return gemini_transcript

        # ── Secondary: Groq Whisper API ──
        if not self.api_key:
            logger.warning("No GROQ_API_KEY configured — skipping audio transcription.")
            return None

        try:
            headers = {"Authorization": f"Bearer {self.api_key}"}

            with open(audio_filepath, "rb") as audio_file:
                files = {"file": (os.path.basename(audio_filepath), audio_file, "audio/mpeg")}
                data = {
                    "model": "whisper-large-v3-turbo",
                    "response_format": "json",
                }

                async with httpx.AsyncClient(timeout=30.0) as client:
                    res = await client.post(GROQ_WHISPER_URL, headers=headers, data=data, files=files)

                    if res.status_code == 200:
                        res_json = res.json()
                        transcript = res_json.get("text", "").strip()
                        logger.info(f"Whisper transcription SUCCESS ({len(transcript)} chars): '{transcript[:60]}...'")
                        return transcript
                    else:
                        logger.warning(f"Groq Whisper HTTP {res.status_code}: {res.text}")
                        return None

        except Exception as e:
            logger.error(f"Whisper API transcription error: {e}")
            return None
        finally:
            # Clean up temp audio file
            try:
                if os.path.exists(audio_filepath):
                    os.remove(audio_filepath)
            except Exception:
                pass

    async def transcribe_post_video_if_needed(
        self,
        post_url: Optional[str],
        current_caption: str,
        min_caption_len: int = 500
    ) -> str:
        """Download and transcribe video audio for Instagram Reels & TikTok posts if caption is under min_caption_len."""
        if not post_url:
            return current_caption

        # If caption is already extremely detailed (>500 chars), skip extra audio download to save bandwidth
        if len(current_caption.strip()) >= min_caption_len:
            return current_caption

        logger.info(f"Short caption detected ({len(current_caption)} chars). Transcribing video audio for {post_url}...")
        
        # Download audio track in background thread to avoid blocking loop
        audio_path = await asyncio.to_thread(self.download_audio_from_url, post_url)
        if not audio_path:
            return current_caption

        transcript = await self.transcribe_audio_file(audio_path)
        if transcript and len(transcript) > 5:
            return f"{current_caption}\n\n🎙️ [Video Audio Transcript]:\n{transcript}"

        return current_caption
