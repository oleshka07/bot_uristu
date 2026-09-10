"""Провайдери дописів із соцмереж: «дай останні N дописів цього профілю».

Той самий шов, що й у ``connector.py`` для знімків профілю: платформа ->
функція. Перший провайдер — Apify. Обрано його, а не бібліотеки на кшталт
instagram4j чи php-scraper, з однієї причини: ті працюють через *твій*
залогінений акаунт і ризикують ним, а керований скрапер ходить своїми
проксі й бере гроші за результат, не за ризик.

Заміна провайдера — це заміна однієї функції в реєстрі, решта коду не знає,
звідки прийшли дописи.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.core.config import settings

logger = logging.getLogger("networking.social.posts")


@dataclass
class PostData:
    external_id: str
    url: str | None
    caption: str | None
    alt_text: str | None
    media_type: str | None
    posted_at: datetime | None


def instagram_handle(url: str | None) -> str | None:
    """`https://www.instagram.com/olena.k/` -> `olena.k`. Порожньо, якщо не профіль."""
    if not url:
        return None
    path = urlparse(url if "://" in url else f"https://{url}").path.strip("/")
    first = path.split("/")[0] if path else ""
    if not first or first in {"p", "reel", "reels", "stories", "explore", "accounts"}:
        return None
    return first.lstrip("@")


def _parse_ts(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _media_type(raw) -> str | None:
    value = str(raw or "").lower()
    if not value:
        return None
    # Instagram називає рілси «clips» у productType — це теж відео.
    if "video" in value or "reel" in value or "clip" in value:
        return "video"
    if "sidecar" in value or "carousel" in value:
        return "carousel"
    return "image"


def parse_apify_items(items: list[dict]) -> list[PostData]:
    """Толерантно читає елементи датасету: назви ключів у акторів гуляють."""
    out: list[PostData] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        external_id = str(item.get("id") or item.get("shortCode") or item.get("shortcode") or "")
        if not external_id:
            continue
        out.append(
            PostData(
                external_id=external_id,
                url=item.get("url") or item.get("postUrl"),
                caption=(item.get("caption") or item.get("text") or None),
                alt_text=(item.get("alt") or item.get("accessibilityCaption") or None),
                media_type=_media_type(item.get("type") or item.get("productType")),
                posted_at=_parse_ts(item.get("timestamp") or item.get("takenAt") or item.get("taken_at")),
            )
        )
    return out


def fetch_instagram_posts_apify(profile_url: str, *, limit: int | None = None) -> list[PostData]:
    """Останні дописи профілю через Apify (синхронний запуск, датасет у відповіді).

    Ніколи не кидає: без токена або при збої повертає порожній список, а
    монітор просто піде далі. Вхідні ключі актора (`directUrls`, `resultsType`,
    `resultsLimit`) — звірити один раз із його сторінкою при підключенні.
    """
    token = settings.apify_api_token
    if not token:
        return []
    actor = settings.apify_instagram_actor
    limit = limit or settings.social_monitor_posts_limit
    payload = {
        "directUrls": [profile_url],
        "resultsType": "posts",
        "resultsLimit": limit,
        "addParentData": False,
    }
    try:
        with httpx.Client(timeout=180.0) as client:
            resp = client.post(
                f"https://api.apify.com/v2/acts/{actor}/run-sync-get-dataset-items",
                params={"token": token, "timeout": 150, "memory": 1024},
                json=payload,
            )
            resp.raise_for_status()
            return parse_apify_items(resp.json())
    except Exception as exc:
        logger.warning("apify instagram fetch failed for %s: %s", profile_url, exc)
        return []


# ── Реєстр ───────────────────────────────────────────────────────────────────

_PROVIDERS: dict[str, "callable"] = {}


def register_post_provider(platform: str, func) -> None:
    _PROVIDERS[platform] = func


def fetch_posts(platform: str, profile_url: str) -> list[PostData]:
    provider = _PROVIDERS.get(platform)
    if provider is None:
        return []
    try:
        return provider(profile_url)
    except Exception as exc:  # pragma: no cover
        logger.warning("post provider %s failed: %s", platform, exc)
        return []


def configured(platform: str = "instagram") -> bool:
    """Чи є кому ходити по дописи: провайдер зареєстрований і має ключ."""
    if platform == "instagram":
        return bool(settings.apify_api_token)
    return platform in _PROVIDERS


register_post_provider("instagram", fetch_instagram_posts_apify)
