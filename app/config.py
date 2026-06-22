"""Application configuration, loaded from environment / .env file."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # AI
    anthropic_api_key: str | None = None
    ai_model: str = "claude-opus-4-8"

    # Database
    database_url: str = "sqlite:///./networking.db"

    # Behaviour
    daily_suggestions: int = 5
    upcoming_window_days: int = 14

    # CORS
    cors_origins: str = "*"

    # Google integration (Gmail + Calendar sync)
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_redirect_uri: str = "http://localhost:8000/api/integrations/google/callback"
    # How many days back to pull emails / calendar events when syncing.
    sync_window_days: int = 120

    # Daily automation (background scheduler)
    scheduler_enabled: bool = False
    daily_run_hour: int = 8  # local server hour to run the daily job
    digest_email_to: str | None = None  # where to send the daily digest

    # Social scraping provider (for JS-heavy networks)
    scraper_provider: str | None = None  # e.g. "scrapingbee"
    scraper_api_key: str | None = None

    # AI sentiment scoring of synced interactions (emails/meetings/telegram)
    sync_ai_sentiment: bool = True

    # Chater importer (reuse the existing Telegram bot's database)
    chater_database_url: str | None = None

    # Telegram (digest delivery + lightweight command bot)
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)

    @property
    def chater_configured(self) -> bool:
        return bool(self.chater_database_url)

    @property
    def telegram_configured(self) -> bool:
        return bool(self.telegram_bot_token)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
