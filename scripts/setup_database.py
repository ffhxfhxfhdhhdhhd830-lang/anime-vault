import asyncio
from anime_vault.config import Settings
from anime_vault.database import Database

async def main():
    cfg = Settings.from_env(); db = Database(cfg.mongodb_uri, cfg.database)
    try:
        await db.ensure_indexes(); await db.ping()
        print(f"MongoDB indexes ready for database {cfg.database}.")
    finally: await db.close()

if __name__ == "__main__": asyncio.run(main())
