from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    bot_token: str
    mongodb_uri: str
    database: str
    owner_id: int
    allowed_user_ids: tuple[int, ...]
    region: str = "IN"
    timezone: str = "Asia/Kolkata"
    tmdb_api_key: str | None = None
    omdb_api_key: str | None = None
    anilist_enabled: bool = True
    log_level: str = "INFO"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        token, uri = os.getenv("BOT_TOKEN", "").strip(), os.getenv("MONGODB_URI", "").strip()
        raw_owner = os.getenv("OWNER_TELEGRAM_ID", "").strip()
        if not token:
            raise ValueError("BOT_TOKEN is required")
        if not uri:
            raise ValueError("MONGODB_URI is required")
        if not raw_owner.isdecimal() or int(raw_owner) <= 0:
            raise ValueError("OWNER_TELEGRAM_ID must be a positive numeric Telegram user ID")
        def ids(raw: str) -> tuple[int, ...]:
            try:
                return tuple(dict.fromkeys(int(value.strip()) for value in raw.split(",") if value.strip()))
            except ValueError as exc:
                raise ValueError("ALLOWED_USER_IDS must contain comma-separated numeric IDs") from exc
        return cls(token, uri, os.getenv("MONGODB_DATABASE", "anime_vault"), int(raw_owner),
                   ids(os.getenv("ALLOWED_USER_IDS", "")), os.getenv("DEFAULT_REGION", "IN").upper(),
                   os.getenv("TIMEZONE", "Asia/Kolkata"), os.getenv("TMDB_API_KEY") or None,
                   os.getenv("OMDB_API_KEY") or None, True, os.getenv("LOG_LEVEL", "INFO").upper())
