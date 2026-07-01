"""Social import connectors.

A pluggable framework for pulling public information from a contact's social
links. Today it ships a best-effort generic fetcher (HTTP + HTML parsing) that
captures whatever a public page exposes (Open Graph / meta / visible text).

Many networks (Instagram, LinkedIn) gate content behind auth or anti-scraping.
The connector registry below is the seam where authenticated scrapers, official
APIs, or third-party data providers get plugged in later — without changing the
rest of the app. Each connector just needs to return a `SnapshotData`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx

from app.core.config import settings

logger = logging.getLogger("networking.social")

_USER_AGENT = (
    "Mozilla/5.0 (compatible; NetworkingAI/0.1; +https://example.com/bot)"
)


@dataclass
class SnapshotData:
    platform: str
    url: str
    title: str | None
    raw_text: str | None


PLATFORM_HOSTS = {
    "instagram.com": "instagram",
    "facebook.com": "facebook",
    "fb.com": "facebook",
    "linkedin.com": "linkedin",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "github.com": "github",
    "t.me": "telegram",
}


def detect_platform(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    for domain, platform in PLATFORM_HOSTS.items():
        if host == domain or host.endswith("." + domain):
            return platform
    return "web"


def _parse_html(url: str, html: str, platform: str) -> SnapshotData:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")

    def meta(prop: str) -> str | None:
        tag = soup.find("meta", attrs={"property": prop}) or soup.find(
            "meta", attrs={"name": prop}
        )
        if tag and tag.get("content"):
            return tag["content"].strip()
        return None

    title = meta("og:title") or (soup.title.string.strip() if soup.title and soup.title.string else None)
    description = meta("og:description") or meta("description")

    # Fall back to visible body text (trimmed) so the AI always has something.
    body_text = None
    if not description:
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())
        body_text = text[:2000] if text else None

    raw_text = description or body_text
    return SnapshotData(platform=platform, url=url, title=title, raw_text=raw_text)


def fetch_generic(url: str) -> SnapshotData:
    """Best-effort fetch of a public page. Never raises — returns a snapshot
    with whatever could be gathered (possibly empty)."""
    platform = detect_platform(url)
    try:
        with httpx.Client(
            timeout=15.0,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Accept-Language": "en"},
        ) as client:
            resp = client.get(url)
            resp.raise_for_status()
            return _parse_html(url, resp.text, platform)
    except Exception as exc:
        logger.info("Generic social fetch failed for %s: %s", url, exc)
        return SnapshotData(
            platform=platform,
            url=url,
            title=None,
            raw_text=(
                "Could not fetch public content automatically. This platform "
                "likely requires an authenticated connector. The link is saved "
                "and ready for a dedicated connector."
            ),
        )


# ── Connector registry ───────────────────────────────────────────────────────
# Map a platform name to a callable(url) -> SnapshotData. Register richer,
# authenticated connectors here as they are built.

Connector = "Callable[[str], SnapshotData]"
_CONNECTORS: dict[str, "Connector"] = {}


def register_connector(platform: str, func) -> None:
    _CONNECTORS[platform] = func


def fetch_snapshot(url: str) -> SnapshotData:
    """Fetch using a platform-specific connector if registered, else generic."""
    platform = detect_platform(url)
    connector = _CONNECTORS.get(platform)
    if connector is not None:
        try:
            return connector(url)
        except Exception as exc:  # pragma: no cover
            logger.warning("Connector for %s failed: %s", platform, exc)
    # A configured scraping provider can render JS-heavy public pages.
    if settings.scraper_provider and settings.scraper_api_key:
        return fetch_with_scraper(url)
    return fetch_generic(url)


# ── Scraping-provider connector (renders JS) ─────────────────────────────────


def fetch_with_scraper(url: str) -> SnapshotData:
    """Fetch a page through a rendering scraper API (currently ScrapingBee).

    This is what makes Instagram / LinkedIn / Facebook public pages actually
    yield content, since they require JavaScript. Configure via
    SCRAPER_PROVIDER + SCRAPER_API_KEY. Falls back to the generic fetch.
    """
    platform = detect_platform(url)
    provider = (settings.scraper_provider or "").lower()
    try:
        if provider == "scrapingbee":
            with httpx.Client(timeout=45.0) as client:
                resp = client.get(
                    "https://app.scrapingbee.com/api/v1/",
                    params={
                        "api_key": settings.scraper_api_key,
                        "url": url,
                        "render_js": "true",
                        "wait": "2500",
                    },
                )
                resp.raise_for_status()
                return _parse_html(url, resp.text, platform)
        logger.info("Unknown scraper provider '%s'; using generic fetch.", provider)
    except Exception as exc:
        logger.info("Scraper fetch failed for %s: %s", url, exc)
    return fetch_generic(url)
