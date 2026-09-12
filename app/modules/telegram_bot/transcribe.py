"""Розшифровка голосових: Deepgram → Whisper → Gemini.

Порядок задається `TRANSCRIBE_PROVIDER` (порожньо = «перший, у кого є ключ»,
у наведеному порядку). Deepgram стоїть першим навмисно: у власника там
окремий баланс, і він хоче витрачати саме його, а не токени OpenAI.

Повертає None, коли жоден провайдер не налаштований або всі впали — викликач
деградує мʼяко: голосове все одно доходить до власника, лише без тексту.
"""

from __future__ import annotations

import base64
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("networking.transcribe")

PROVIDERS = ("deepgram", "openai", "gemini")


def available_providers() -> list[str]:
    """Хто має ключ — у порядку, в якому їх пробуватимемо."""
    keys = {
        "deepgram": settings.deepgram_api_key,
        "openai": settings.openai_api_key,
        "gemini": settings.gemini_api_key,
    }
    preferred = (settings.transcribe_provider or "").lower().strip()
    order = [p for p in PROVIDERS if keys.get(p)]
    if preferred in order:
        order.remove(preferred)
        order.insert(0, preferred)
    return order


def active_provider() -> str | None:
    order = available_providers()
    return order[0] if order else None


def transcribe_ogg(audio: bytes) -> str | None:
    for provider in available_providers():
        text = _CALLERS[provider](audio)
        if text:
            return text
    return None


def _deepgram(audio: bytes) -> str | None:
    """Deepgram prerecorded: один POST із сирим аудіо, мова визначається сама.

    `detect_language` замість жорсткої `uk`: власнику пишуть і російською,
    і англійською, а розшифровка чужою мовою — це сміття, а не текст.
    """
    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                "https://api.deepgram.com/v1/listen",
                params={
                    "model": settings.deepgram_model,
                    "smart_format": "true",
                    "detect_language": "true",
                },
                headers={
                    "Authorization": f"Token {settings.deepgram_api_key}",
                    "Content-Type": "audio/ogg",
                },
                content=audio,
            )
            resp.raise_for_status()
            data = resp.json()
            alternatives = data["results"]["channels"][0]["alternatives"]
            text = (alternatives[0].get("transcript") or "").strip()
            return text or None
    except Exception as exc:  # pragma: no cover - network
        logger.warning("Deepgram transcription failed: %s", exc)
        return None


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


_CALLERS = {"deepgram": _deepgram, "openai": _whisper, "gemini": _gemini}
