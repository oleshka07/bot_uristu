"""Voice-note transcription: OpenAI Whisper first, Gemini fallback.

Same provider order and keys as Chater used, so the existing keys carry
over. Returns None when no provider is configured or all fail — callers
degrade gracefully (the raw voice note still reaches the admin).
"""

from __future__ import annotations

import base64
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("networking.transcribe")


def transcribe_ogg(audio: bytes) -> str | None:
    text = _whisper(audio) if settings.openai_api_key else None
    if text:
        return text
    if settings.gemini_api_key:
        return _gemini(audio)
    return text


def _whisper(audio: bytes) -> str | None:
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                data={"model": "whisper-1", "language": "uk"},
                files={"file": ("voice.ogg", audio, "audio/ogg")},
            )
            resp.raise_for_status()
            return (resp.json().get("text") or "").strip() or None
    except Exception as exc:  # pragma: no cover - network
        logger.warning("Whisper transcription failed: %s", exc)
        return None


def _gemini(audio: bytes) -> str | None:
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{settings.gemini_model}:generateContent",
                params={"key": settings.gemini_api_key},
                json={
                    "contents": [
                        {
                            "parts": [
                                {
                                    "text": (
                                        "Розшифруй це голосове повідомлення. "
                                        "Поверни лише текст, без коментарів."
                                    )
                                },
                                {
                                    "inline_data": {
                                        "mime_type": "audio/ogg",
                                        "data": base64.b64encode(audio).decode(),
                                    }
                                },
                            ]
                        }
                    ]
                },
            )
            resp.raise_for_status()
            data = resp.json()
            parts = data["candidates"][0]["content"]["parts"]
            text = " ".join(p.get("text", "") for p in parts).strip()
            return text or None
    except Exception as exc:  # pragma: no cover - network
        logger.warning("Gemini transcription failed: %s", exc)
        return None
