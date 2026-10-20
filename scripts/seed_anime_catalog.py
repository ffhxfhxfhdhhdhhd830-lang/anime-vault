from __future__ import annotations

import argparse
import asyncio
import json
import logging

from anime_vault.catalog import entries
from anime_vault.config import Settings
from anime_vault.database import Database
from anime_vault.services import CatalogService, MetadataEnricher


async def run(args) -> int:
    cfg = Settings.from_env()
    db = Database(cfg.mongodb_uri, cfg.database)
    try:
        await db.ensure_indexes()
        report = await CatalogService(db.db).seed(entries(), dry_run=args.dry_run)
        if args.enrich:
            updated, failures = await MetadataEnricher(db.db).enrich_incomplete(args.limit)
            report["metadata_enriched"] = updated
            report["metadata_lookup_failures"] = failures
        print(json.dumps(report, indent=2, default=str))
        return 0
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely seed Anime Vault's shared anime catalog.")
    parser.add_argument("--dry-run", action="store_true", help="Report inserts and enrichments without writing")
    parser.add_argument("--enrich", action="store_true", help="Retry incomplete metadata lookups")
    parser.add_argument("--limit", type=int, default=50, help="Maximum entries to enrich in this run")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        logging.getLogger(__name__).error("Catalog job failed (%s)", type(exc).__name__)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
