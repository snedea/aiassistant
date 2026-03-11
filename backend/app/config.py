from __future__ import annotations
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # LLM
    ollama_base_url: str = "http://ollama:11434"
    ollama_chat_model: str = "llama3.2"
    ollama_embed_model: str = "nomic-embed-text"

    # Calendar
    caldav_url: str = ""
    caldav_username: str = ""
    caldav_password: str = ""

    # Email
    imap_host: str = ""
    imap_port: int = 993
    imap_username: str = ""
    imap_password: str = ""

    # Notifications
    slack_webhook_url: str = ""
    slack_bot_token: str = ""
    slack_app_token: str = ""
    slack_allowed_user_ids: str = ""

    # iMessage (macOS only, via osascript)
    imessage_recipient: str = ""  # phone number or email for iMessage

    # Quiet hours (24h format in local time, e.g. "22:00" to "07:00")
    quiet_hours_start: str = ""
    quiet_hours_end: str = ""
    quiet_hours_bypass_urgent: bool = True

    # Scanner intervals
    calendar_scan_interval_min: int = 5
    email_scan_interval_min: int = 10
    notes_scan_interval_min: int = 30
    event_alert_window_min: int = 15

    # Daily digest
    digest_enabled: bool = True
    digest_hour: int = 7  # Hour in local time (0-23) to send the daily digest

    # Source health monitoring
    health_check_interval_min: int = 5  # How often to check source health (minutes)
    health_stale_multiplier: float = 3.0  # Source is "stale" if no sync in interval * multiplier
    health_alert_cooldown_min: int = 60  # Don't re-alert for same source within this window

    # LLM Rate Limiting & Token Budget
    llm_daily_token_budget: int = 500000  # Max estimated tokens per day (0 = unlimited)
    llm_rate_limit_rpm: int = 30  # Max LLM requests per minute (0 = unlimited)
    llm_budget_warning_pct: int = 80  # Warn when this % of daily budget is consumed

    # Database
    database_url: str = "sqlite:///data/assistant.db"
    chroma_persist_dir: str = "./data/chroma"

    # Authentication
    api_key: str = ""  # Empty = auth disabled (dev mode)

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
