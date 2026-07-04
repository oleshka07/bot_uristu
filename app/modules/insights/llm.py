"""Provider-agnostic LLM calls: Anthropic / OpenAI / Gemini with fallback.

One tiny surface — ``text()``, ``json()``, ``vision_json()`` — that every AI
feature calls. The provider order is ``settings.ai_provider`` first, then any
other provider that has a key, so if the primary is out of credit (or down)
the call transparently falls back. Each helper returns ``None`` on total
failure, and callers already degrade to rule-based fallbacks.
"""

from __future__ import annotations

import base64
import json as _json
import logging

import httpx

from app.core.config import settings

logger = logging.getLogger("networking.llm")

_anthropic = None


# ── Provider selection ───────────────────────────────────────────────────────


def _has_key(provider: str) -> bool:
    return bool(
        {
            "anthropic": settings.anthropic_api_key,
            "openai": settings.openai_api_key,
            "gemini": settings.gemini_api_key,
        }.get(provider)
    )


def providers_in_order() -> list[str]:
    primary = (settings.ai_provider or "anthropic").lower()
    order: list[str] = []
    for p in [primary, "anthropic", "openai", "gemini"]:
        if p not in order and _has_key(p):
            order.append(p)
    return order


def enabled() -> bool:
    return bool(providers_in_order())


def active_provider() -> str | None:
    order = providers_in_order()
    return order[0] if order else None


# ── JSON parsing (forgiving) ─────────────────────────────────────────────────


def _loads(text: str | None):
    if not text:
        return None
    try:
        return _json.loads(text)
    except _json.JSONDecodeError:
        for opener, closer in (("{", "}"), ("[", "]")):
            start, end = text.find(opener), text.rfind(closer)
            if start != -1 and end > start:
                try:
                    return _json.loads(text[start : end + 1])
                except _json.JSONDecodeError:
                    continue
    return None


# ── Per-provider raw text call ───────────────────────────────────────────────


def _anthropic_call(system, user, max_tokens, thinking, schema, image, mime) -> str | None:
    global _anthropic
    if _anthropic is None:
        import anthropic

        _anthropic = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    if image is not None:
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": mime,
                    "data": base64.b64encode(image).decode(),
                },
            },
            {"type": "text", "text": user},
        ]
    else:
        content = user
    kwargs = {
        "model": settings.ai_model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": content}],
    }
    if thinking:
        kwargs["thinking"] = {"type": "adaptive"}
    if schema is not None:
        kwargs["output_config"] = {
            "format": {"type": "json_schema", "schema": schema}
        }
    resp = _anthropic.messages.create(**kwargs)
    return "".join(
        b.text for b in resp.content if getattr(b, "type", None) == "text"
    ).strip()


def _openai_call(system, user, max_tokens, thinking, schema, image, mime) -> str | None:
    if image is not None:
        user_content = [
            {"type": "text", "text": user},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:{mime};base64,{base64.b64encode(image).decode()}"
                },
            },
        ]
    else:
        user_content = user
    body = {
        "model": settings.openai_model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
    }
    if schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "result", "strict": True, "schema": schema},
        }
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json=body,
        )
        resp.raise_for_status()
        return (resp.json()["choices"][0]["message"]["content"] or "").strip()


def _gemini_call(system, user, max_tokens, thinking, schema, image, mime) -> str | None:
    parts = [{"text": f"{system}\n\n{user}"}]
    if image is not None:
        parts.append(
            {
                "inline_data": {
                    "mime_type": mime,
                    "data": base64.b64encode(image).decode(),
                }
            }
        )
    body = {
        "contents": [{"parts": parts}],
        "generationConfig": {"maxOutputTokens": max_tokens},
    }
    if schema is not None:
        body["generationConfig"]["response_mime_type"] = "application/json"
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{settings.gemini_model}:generateContent",
            params={"key": settings.gemini_api_key},
            json=body,
        )
        resp.raise_for_status()
        cand = resp.json()["candidates"][0]["content"]["parts"]
        return " ".join(p.get("text", "") for p in cand).strip()


_DISPATCH = {
    "anthropic": _anthropic_call,
    "openai": _openai_call,
    "gemini": _gemini_call,
}


def _raw(system, user, *, max_tokens, thinking=False, schema=None, image=None, mime=None):
    """Try each provider in order; return the first non-empty response."""
    for provider in providers_in_order():
        try:
            out = _DISPATCH[provider](
                system, user, max_tokens, thinking, schema, image, mime
            )
            if out:
                return out
        except Exception as exc:  # pragma: no cover - network/credentials
            logger.warning("LLM provider %s failed: %s", provider, exc)
    return None


# ── Public surface ───────────────────────────────────────────────────────────


def text(system: str, user: str, *, max_tokens: int = 1000, thinking: bool = False):
    return _raw(system, user, max_tokens=max_tokens, thinking=thinking)


def json(system: str, user: str, schema: dict, *, max_tokens: int = 1200, thinking: bool = False):
    return _loads(
        _raw(system, user, max_tokens=max_tokens, thinking=thinking, schema=schema)
    )


def vision_json(
    system: str, user: str, image: bytes, mime: str, schema: dict, *, max_tokens: int = 600
):
    return _loads(
        _raw(system, user, max_tokens=max_tokens, schema=schema, image=image, mime=mime)
    )


# ── Embeddings (OpenAI / Voyage — Anthropic has no embeddings API) ────────────


def embeddings_enabled() -> bool:
    return bool(settings.openai_api_key or settings.voyage_api_key)


def embeddings_model() -> str:
    return settings.embeddings_model


def embed(texts: list[str], *, input_type: str = "document") -> list[list[float]] | None:
    """Embed a batch of texts. Returns one vector per text, or None on
    failure / when no embeddings provider is configured."""
    if not texts:
        return []
    try:
        if settings.openai_api_key:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                    json={"model": settings.embeddings_model, "input": texts},
                )
                resp.raise_for_status()
                data = sorted(resp.json()["data"], key=lambda d: d["index"])
                return [d["embedding"] for d in data]
        if settings.voyage_api_key:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    "https://api.voyageai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {settings.voyage_api_key}"},
                    json={
                        "model": settings.embeddings_model,
                        "input": texts,
                        "input_type": input_type,
                    },
                )
                resp.raise_for_status()
                data = sorted(resp.json()["data"], key=lambda d: d["index"])
                return [d["embedding"] for d in data]
    except Exception as exc:  # pragma: no cover - network
        logger.warning("embed failed: %s", exc)
    return None
