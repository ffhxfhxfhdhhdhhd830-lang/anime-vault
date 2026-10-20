from __future__ import annotations

import json
from typing import Any

from .models import Status, now_utc

ALLOWED_FIELDS = {"title_id", "status", "progress", "rating", "notes", "favourite", "custom_list_ids", "added_at", "completed_at"}


def parse_export(raw: bytes, acting_user_id: int) -> list[dict[str, Any]]:
    if len(raw) > 5_000_000:
        raise ValueError("File is larger than 5 MB")
    try:
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("File is not valid UTF-8 JSON") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1 or data.get("user_id") != acting_user_id:
        raise ValueError("Unsupported export or export belongs to a different Telegram user")
    rows = data.get("library")
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("Library must be a list of at most 10,000 records")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Each library record must be an object")
        item = {k: v for k, v in row.items() if k in ALLOWED_FIELDS}
        tid, status = item.get("title_id"), item.get("status")
        if not isinstance(tid, str) or not tid or tid in seen:
            raise ValueError("Each record needs a unique string title_id")
        seen.add(tid)
        if status not in {s.value for s in Status}:
            raise ValueError(f"Invalid status in record {tid}")
        progress = item.get("progress", 0)
        rating = item.get("rating")
        if not isinstance(progress, int) or isinstance(progress, bool) or progress < 0:
            raise ValueError(f"Invalid progress in record {tid}")
        if rating is not None and (not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 10):
            raise ValueError(f"Invalid rating in record {tid}")
        if not isinstance(item.get("notes", ""), str) or not isinstance(item.get("favourite", False), bool):
            raise ValueError(f"Invalid notes or favourite value in record {tid}")
        item["title_id"] = tid
        result.append(item)
    return result


async def preview_import(db, user_id: int, rows: list[dict]) -> dict[str, int]:
    result = {"inserted": 0, "updated": 0, "skipped": 0, "rejected": 0}
    for row in rows:
        if not await db.titles.find_one({"_id": row["title_id"]}):
            result["rejected"] += 1
        elif await db.user_library.find_one({"user_id": user_id, "title_id": row["title_id"]}):
            result["skipped"] += 1
        else:
            result["inserted"] += 1
    return result


async def apply_import(db, user_id: int, rows: list[dict]) -> dict[str, int]:
    result = {"inserted": 0, "updated": 0, "skipped": 0, "rejected": 0}
    for row in rows:
        if not await db.titles.find_one({"_id": row["title_id"]}):
            result["rejected"] += 1
            continue
        data = {k: v for k, v in row.items() if k in ALLOWED_FIELDS}
        data.update(user_id=user_id, imported_at=now_utc())
        write = await db.user_library.update_one({"user_id": user_id, "title_id": row["title_id"]}, {"$setOnInsert": data}, upsert=True)
        if write.upserted_id is not None: result["inserted"] += 1
        else: result["skipped"] += 1
    return result
