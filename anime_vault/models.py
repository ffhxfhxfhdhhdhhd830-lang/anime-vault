from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class Status(StrEnum):
    PLAN_TO_WATCH = "PLAN_TO_WATCH"
    WATCHING = "WATCHING"
    WATCHED = "WATCHED"
    ON_HOLD = "ON_HOLD"
    DROPPED = "DROPPED"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def canonical_id(title: str, format_: str) -> str:
    import re, unicodedata, hashlib
    value = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    digest = hashlib.sha256(f"{format_}:{value}".encode()).hexdigest()[:20]
    return f"av:{digest}"


def title_document(title: str, category: str, format_: str, **metadata: Any) -> dict[str, Any]:
    return {"_id": canonical_id(title, format_), "title": title, "format": format_,
            "categories": [category], "genres": [], "alternative_titles": [],
            "metadata_status": "incomplete", "metadata_source": None,
            "created_at": now_utc(), "updated_at": now_utc(), **metadata}
