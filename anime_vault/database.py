from __future__ import annotations

from pymongo import ASCENDING, IndexModel
from pymongo.errors import PyMongoError
from pymongo.asynchronous.mongo_client import AsyncMongoClient


class Database:
    def __init__(self, uri: str, name: str):
        self.client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5000, tz_aware=True)
        self.db = self.client[name]

    async def ping(self) -> bool:
        await self.db.command("ping")
        return True

    async def ensure_indexes(self) -> None:
        await self.db.titles.create_indexes([
            IndexModel([("title", ASCENDING)]), IndexModel([("alternative_titles", ASCENDING)]),
            IndexModel([("categories", ASCENDING), ("title", ASCENDING)]),
            IndexModel([("external_ids.anilist", ASCENDING)], unique=True, sparse=True),
            IndexModel([("external_ids.tmdb", ASCENDING)], unique=True, sparse=True),
            IndexModel([("external_ids.mal", ASCENDING)], unique=True, sparse=True),
        ])
        await self.db.user_library.create_index([("user_id", ASCENDING), ("title_id", ASCENDING)], unique=True)
        await self.db.authorized_users.create_index([("user_id", ASCENDING)], unique=True)
        await self.db.custom_lists.create_index([("user_id", ASCENDING), ("name", ASCENDING)], unique=True)
        await self.db.watch_progress.create_index([("user_id", ASCENDING), ("title_id", ASCENDING)], unique=True)
        await self.db.watch_history.create_index([("user_id", ASCENDING), ("created_at", -1)])
        await self.db.reminders.create_index([("user_id", ASCENDING), ("due_at", ASCENDING), ("sent_at", ASCENDING)])

    async def close(self) -> None:
        await self.client.close()
