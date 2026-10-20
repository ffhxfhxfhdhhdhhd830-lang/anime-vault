# Anime Vault

Anime Vault is a private Telegram anime tracker backed by MongoDB. The app keeps shared title metadata in `titles` and each person's statuses, ratings, favourites, notes, and progress in separate user-owned collections. Catalog seeding never inserts titles into anyone's library.

## Requirements

- Python 3.11+ (Python 3.12 recommended)
- MongoDB 7+ or a compatible MongoDB deployment that supports transactions/indexes as configured
- Telegram bot token from [@BotFather](https://t.me/BotFather)
- MongoDB connection string for a database you control

The bot uses asynchronous `python-telegram-bot` and PyMongo's async `AsyncMongoClient`; it does not use Motor. No external provider key is required for basic catalog use.

## Install and configure

1. Create and activate a virtual environment: `python -m venv .venv` then activate it for your shell.
2. Install dependencies: `python -m pip install -r requirements.txt`.
3. Copy `.env.example` to `.env` and fill in `BOT_TOKEN`, `MONGODB_URI`, and your numeric `OWNER_TELEGRAM_ID`. The owner ID is mandatory; without it the application fails closed.
4. Optionally set comma-separated `ALLOWED_USER_IDS`; the owner can also approve users from Telegram.
5. Create indexes with `python -m scripts.setup_database`.
6. Seed the recommendations safely with `python -m scripts.seed_anime_catalog --dry-run`, inspect the report, then execute with `python -m scripts.seed_anime_catalog`.
7. Start polling with `python app.py`.

Keep `.env`, database backups, and exported library files private. The bot is intended for a persistent Python service with one polling instance per bot token. Configure secrets through the service's secret manager and keep MongoDB credentials least-privileged.

## MongoDB collections

- `titles`: shared canonical metadata; deterministic stable IDs and sparse unique provider ID indexes.
- `user_library`: one unique entry per `(user_id, title_id)` with status, progress summary, rating, notes, favourite state, and timestamps.
- `watch_progress`: episode progress separate from shared metadata.
- `authorized_users`: approved roles; the configured owner is bootstrapped as `OWNER` and cannot be revoked.
- `custom_lists`, `user_settings`, `reminders`, `streaming_availability`: user preferences and optional future/provider data.

Catalog categories describe the recommendation grouping, such as `romance_movies`; genres are provider metadata and are not inferred from the recommendation label. Cross-category records are represented by one title with multiple category values. The Promised Neverland has a `season_1` recommendation tag while remaining one title. Normalized deterministic internal IDs collapse category overlaps and punctuation variants; ambiguous sequel/season matches are kept separate for manual review.

## Catalog maintenance

- `python -m scripts.seed_anime_catalog --dry-run`: inspect inserts and enrichments without modifying data.
- `python -m scripts.seed_anime_catalog`: upsert shared titles and enrich only missing fields. Existing metadata and every user library record are preserved.
- `python -m scripts.seed_anime_catalog --enrich --limit 50`: seed and retry incomplete metadata lookups.
- Telegram owner commands: `/seed_catalog` (dry run); `/seed_catalog --execute`; `/catalog_stats`; `/catalog_incomplete`; `/enrich_catalog`; `/add_recommendations_to_library`.
- The UI has **🎌 Recommendation Catalog**, category browsing, title search and pagination. “Add All Recommendations” is owner-only and requires confirmation; it inserts only missing `PLAN_TO_WATCH` entries.

### Metadata and streaming providers

AniList's public GraphQL endpoint is used for best-effort enrichment when explicitly requested. It has bounded concurrency and timeouts; lookup failures remain incomplete and retryable. Provider-specific IDs and source are stored only when returned. `TMDB_API_KEY` and `OMDB_API_KEY` are placeholders for future authorized adapters; IMDb pages are never scraped. Streaming availability is not asserted without a licensed/configured provider. `/where_to_watch` states when availability is not verified. Configure region with `/setregion IN` (two-letter code).

Provider availability, attribution, caching limits, and access terms depend on the provider account; check those terms before enabling a provider. No streaming service is claimed to carry an anime without reliable data.

## Bot commands

The keyboard exposes main navigation, catalog categories, library, status filters, favourites, statistics, random Plan to Watch selection, local recommendations, and custom lists. Commands include `/start`, `/help`, `/menu`, `/search`, `/add`, `/library`, `/watchlist`, `/watching`, `/watched`, `/onhold`, `/dropped`, `/continue`, `/recent`, `/progress <title> <episodes>`, `/rate <title> <1-10>`, `/review <title> <text>`, `/rewatch <title>`, `/history`, `/recommend`, `/similar <title>`, `/genres`, `/lists`, `/create_list <name>`, `/rename_list old | new`, `/delete_list <name>`, `/move_list_item list | title | position`, `/stats`, `/export`, `/import`, `/reminders`, `/settings`, `/where_to_watch <title>`, `/setregion`, and `/cancel`.

Owner-only commands: `/allow <id> [USER|ADMIN]`, `/revoke <id>`, `/users`, `/role <id>`, `/backup`, `/health`, `/adminstats`, plus the catalog commands above. Each command and callback rechecks authorization. Numeric Telegram IDs, never usernames, identify users.

## Exports, backups, reminders, deployment

`/export` creates a JSON file containing only the requesting user's library. To import, send the exported JSON as a Telegram document: the bot validates that the export belongs to the acting Telegram user, previews inserted/skipped/rejected records, then asks for confirmation. Existing entries are skipped and never overwritten. For a private owner backup in PowerShell, set the URI/database in the shell and run `mongodump --uri $env:MONGODB_URI --db $env:MONGODB_DATABASE --out .\backups\<date>`; protect that directory and test restore with `mongorestore` to an isolated database before production restore. No restore command overwrites live data.

Reminder preferences are stored, but scheduled delivery, quiet hours, and time-specific reminders are not complete. No unsolicited messages are sent. A production service should restart the long-poll process automatically and keep MongoDB reachable; do not run multiple replicas with the same polling token. On Linux, a simple systemd service can run the project with `WorkingDirectory=/opt/anime-vault`, `EnvironmentFile=/opt/anime-vault/.env`, `ExecStart=/opt/anime-vault/.venv/bin/python /opt/anime-vault/app.py`, `Restart=on-failure`, and an unprivileged service account. Keep `.env` readable only by that account (`chmod 600`).

## Tests

Install requirements and run `python -m pytest -q`. Tests use local fakes and do not require Telegram or provider credentials. Live MongoDB integration, live Telegram polling, provider terms, and streaming availability need configured services and are not part of unit tests.

## Feature checklist and limitations

- Implemented: fail-closed owner setup; per-request command/callback access checks; roles and owner approval/revoke; shared catalog of all 145 recommendations; dry-run/upsert seeding; user-data separation; category UI/search/pagination; add-to-library, status, favourites, episode progress, ratings/reviews, local genre/studio recommendations, custom list create/browse/rename/reorder/delete, basic stats/history/rewatch, user-scoped JSON export/import with preview and confirmation; AniList enrichment adapter; indexes; tests.
- Partial: external search and metadata matching (local catalog search is implemented; AniList is used for enrichment); advanced statistics; reminder preferences persist, but scheduled delivery is absent; streaming availability (explicitly unverified absent a licensed provider); TMDb/OMDb/MAL adapters; full database backup/restore workflow; year/episode filters.
- Not implemented: web dashboard, scheduled reminder delivery, licensed regional streaming provider, rich poster delivery, multi-season episode browser, full import merge/overwrite support, provider adapters beyond AniList, and some advanced analytics from the original specification.

Errors
------

- Invalid/missing environment variables: check `.env`; the bot exits before polling if required settings are missing.
- MongoDB unreachable/index errors: check URI/network/credentials, then run `python -m scripts.setup_database`.
- Catalog metadata absent: minimal records still seed; retry with `--enrich` when provider access is available.
- Telegram denial: verify the numeric owner ID and use `/allow` from the owner account.
- No availability: this means no authorized data provider has verified current offers; it is not a claim that no service has the title.
