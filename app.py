from __future__ import annotations

import logging

from anime_vault.bot import build_application
from anime_vault.config import Settings
from anime_vault.database import Database


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        settings = Settings.from_env()
    except ValueError as exc:
        logging.getLogger(__name__).error("Invalid configuration: %s", exc)
        raise SystemExit(2) from exc
    db = Database(settings.mongodb_uri, settings.database)
    app = build_application(settings, db)

    async def initialize(application):
        await db.ensure_indexes()
        await db.db.authorized_users.update_one({"user_id": settings.owner_id}, {"$set": {"user_id": settings.owner_id, "role": "OWNER", "active": True}}, upsert=True)
        for uid in settings.allowed_user_ids:
            await db.db.authorized_users.update_one({"user_id": uid}, {"$setOnInsert": {"user_id": uid, "role": "USER", "active": True}}, upsert=True)
        await db.ping()

    app.post_init = initialize
    app.run_polling(allowed_updates=["message", "callback_query"])


if __name__ == "__main__":
    main()
