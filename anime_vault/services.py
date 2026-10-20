from __future__ import annotations

import asyncio
from difflib import SequenceMatcher
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from .models import Status, now_utc, title_document


def normalize(value: str) -> str:
    value = value.casefold().replace("×", "x").replace("★", " ")
    return re.sub(r"[^a-z0-9]+", "", value)


class CatalogService:
    def __init__(self, db): self.db = db

    async def search(self, query: str = "", category: str | None = None, page: int = 0, size: int = 8):
        filt: dict[str, Any] = {}
        if category: filt["categories"] = category
        if query:
            escaped = re.escape(query.strip())
            filt["$or"] = [{"title": {"$regex": escaped, "$options": "i"}},
                           {"alternative_titles": {"$regex": escaped, "$options": "i"}},
                           {"genres": {"$regex": escaped, "$options": "i"}}]
        total = await self.db.titles.count_documents(filt)
        docs = await self.db.titles.find(filt).sort("title", 1).skip(max(0, page) * size).limit(size).to_list(length=size)
        return docs, total

    async def seed(self, docs: list[dict], dry_run: bool = False) -> dict[str, int]:
        report = dict(input_entries=len(docs), unique_titles=len({d["_id"] for d in docs}), already_present=0,
                      newly_inserted=0, enriched=0, duplicates_reconciled=0, manual_review=0, metadata_lookup_failures=0)
        for doc in docs:
            old = await self.db.titles.find_one({"_id": doc["_id"]})
            if old:
                report["already_present"] += 1
                missing = {k: v for k, v in doc.items() if k not in old and k not in {"created_at", "updated_at"}}
                missing_categories = sorted(set(doc.get("categories", [])) - set(old.get("categories", [])))
                if missing_categories: missing["categories"] = sorted(set(old.get("categories", [])) | set(doc.get("categories", [])))
                if missing:
                    report["enriched"] += 1
                    if not dry_run:
                        await self.db.titles.update_one({"_id": doc["_id"]}, {"$set": {**missing, "updated_at": now_utc()}})
            else:
                if dry_run:
                    report["newly_inserted"] += 1
                else:
                    result = await self.db.titles.update_one({"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True)
                    if result.upserted_id is not None:
                        report["newly_inserted"] += 1
                    else:
                        report["already_present"] += 1
        if not dry_run:
            # Report only database-confirmed inserts/presence after writes complete.
            report["database_total"] = await self.db.titles.count_documents({"_id": {"$in": [d["_id"] for d in docs]}})
        return report

    async def add_to_library(self, user_id: int, title_id: str) -> bool:
        result = await self.db.user_library.update_one({"user_id": user_id, "title_id": title_id},
            {"$setOnInsert": {"user_id": user_id, "title_id": title_id, "status": Status.PLAN_TO_WATCH.value,
             "progress": 0, "rating": None, "notes": "", "favourite": False, "custom_list_ids": [], "added_at": now_utc()}}, upsert=True)
        return result.upserted_id is not None

    async def bulk_add(self, user_id: int) -> tuple[int, int]:
        inserted = skipped = 0
        async for title in self.db.titles.find({}, {"_id": 1}):
            if await self.add_to_library(user_id, title["_id"]): inserted += 1
            else: skipped += 1
        return inserted, skipped

    async def recommendations(self, user_id: int, seed_title_id: str | None = None, limit: int = 8):
        """Small local genre/studio similarity scorer; it does not call an AI service."""
        library = await self.db.user_library.find({"user_id": user_id}, {"title_id": 1, "status": 1, "rating": 1, "favourite": 1}).to_list(length=5000)
        excluded = {r["title_id"] for r in library}
        profile_ids = {r["title_id"] for r in library if r.get("favourite") or (r.get("rating") or 0) >= 8 or r.get("status") == Status.WATCHED.value}
        if seed_title_id:
            seed = await self.db.titles.find_one({"_id": seed_title_id})
            if not seed: return []
            profile_ids.add(seed_title_id)
            excluded.add(seed_title_id)
        seeds = await self.db.titles.find({"_id": {"$in": list(profile_ids)}}).to_list(length=300)
        genre_weights: dict[str, int] = {}; studio_weights: dict[str, int] = {}
        for seed in seeds:
            for genre in seed.get("genres", []): genre_weights[genre] = genre_weights.get(genre, 0) + 2
            for studio in seed.get("studios", []): studio_weights[studio] = studio_weights.get(studio, 0) + 3
        candidates = await self.db.titles.find({"_id": {"$nin": list(excluded)}}).limit(1000).to_list(length=1000)
        ranked=[]
        for title in candidates:
            score=sum(genre_weights.get(g,0) for g in title.get("genres",[]))+sum(studio_weights.get(s,0) for s in title.get("studios",[]))
            if not score: continue
            reason=', '.join(g for g in title.get('genres',[]) if genre_weights.get(g))
            ranked.append((score,title,reason))
        ranked.sort(key=lambda item:(-item[0],item[1].get('title','').casefold()))
        return [{**title,"recommendation_reason":reason or "Similar studio or genre"} for _,title,reason in ranked[:limit]]


class AniListProvider:
    """Public AniList GraphQL adapter. No API key is needed for basic search."""
    endpoint = "https://graphql.anilist.co"
    query = "query ($search: String!) { Media(search: $search, type: ANIME) { id idMal format title { romaji english native } description(asHtml: false) episodes seasonYear genres averageScore status siteUrl coverImage { large } studios(isMain: true) { nodes { name } } } }"
    def __init__(self, client: httpx.AsyncClient | None = None): self.client = client
    async def _request(self, client, name):
        payload={"query": self.query, "variables": {"search": name}}
        for attempt in range(3):
            try:
                response=await client.post(self.endpoint,json=payload)
                if response.status_code==429 or response.status_code>=500:
                    if attempt<2:
                        await asyncio.sleep(.4*(2**attempt)); continue
                response.raise_for_status()
                return response.json().get("data",{}).get("Media")
            except (httpx.TimeoutException,httpx.NetworkError):
                if attempt==2: raise
                await asyncio.sleep(.4*(2**attempt))
        return None
    async def search(self, name: str) -> dict | None:
        if self.client:
            return await self._request(self.client,name)
        async with httpx.AsyncClient(timeout=8) as client:
            return await self._request(client,name)


class MetadataEnricher:
    def __init__(self, db, provider=None): self.db, self.provider = db, provider
    async def enrich_incomplete(self, limit: int = 50) -> tuple[int, int]:
        docs = await self.db.titles.find({"metadata_status": "incomplete"}).limit(limit).to_list(length=limit)
        sem = asyncio.Semaphore(3); updated = failed = 0
        shared_client = httpx.AsyncClient(timeout=8)
        provider = self.provider or AniListProvider(shared_client)
        async def one(doc):
            nonlocal updated, failed
            async with sem:
                try:
                    found = await provider.search(doc["title"])
                    if not found: failed += 1; return
                    titles = found.get("title", {})
                    names = [x for x in (titles.get("english"), titles.get("romaji"), titles.get("native")) if x]
                    if names and max(SequenceMatcher(None, normalize(doc["title"]), normalize(n)).ratio() for n in names) < .82:
                        failed += 1
                        return
                    ext = {k: v for k, v in {"anilist": found.get("id"), "mal": found.get("idMal")}.items() if v}
                    fields = {"metadata_status": "enriched", "metadata_source": "AniList",
                        "metadata_updated_at": now_utc(), "genres": found.get("genres") or [],
                        "original_title": titles.get("native"), "alternative_titles": list(filter(None, [titles.get("romaji"), titles.get("english")])),
                        "synopsis": found.get("description"), "episode_count": found.get("episodes"),
                        "release_year": found.get("seasonYear"), "external_ids": ext,
                        "official_links": [found["siteUrl"]] if found.get("siteUrl") else [],
                        "poster_url": (found.get("coverImage") or {}).get("large"),
                        "studios": [node.get("name") for node in (found.get("studios") or {}).get("nodes", []) if node.get("name")],
                        "release_status": found.get("status"), "anilist_score": found.get("averageScore")}
                    fields = {k: v for k, v in fields.items() if v not in (None, [], "")}
                    fields = {k: v for k, v in fields.items() if k in {"metadata_status", "metadata_source", "metadata_updated_at"} or not doc.get(k)}
                    old_ids = doc.get("external_ids", {})
                    new_ids = {k: v for k, v in ext.items() if not old_ids.get(k)}
                    if new_ids: fields["external_ids"] = {**old_ids, **new_ids}
                    elif "external_ids" in fields: fields.pop("external_ids")
                    if fields:
                        await self.db.titles.update_one({"_id": doc["_id"]}, {"$set": fields}); updated += 1
                except Exception: failed += 1
        try:
            await asyncio.gather(*(one(doc) for doc in docs))
        finally:
            await shared_client.aclose()
        return updated, failed


def progress_percent(watched: int, total: int | None) -> float | None:
    if watched < 0 or (total is not None and (total < 0 or watched > total)):
        raise ValueError("Episode progress must be non-negative and cannot exceed a known total")
    return round(watched * 100 / total, 1) if total else None
