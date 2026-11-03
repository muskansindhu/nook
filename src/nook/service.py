"""Application services shared by the CLI and the TUI. No UI code lives here."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from nook.adapters.registry import build_adapters
from nook.config import Config, load_config
from nook.db import Database
from nook.extraction import ExtractionError, extract_url, sanitize
from nook.models import FeedOptions, SourceError


@dataclass
class SyncResult:
    source_id: str
    status: str = "success"
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    downloaded: int = 0
    error: str | None = None


@dataclass
class Nook:
    cfg: Config = field(default_factory=load_config)

    def __post_init__(self):
        self.db = Database(self.cfg.db_path)
        self.adapters = build_adapters(self.cfg)

    # ---- sync ----------------------------------------------------------
    async def sync_source(self, sid: str, limit: int, kind: str | None = None, tag: str | None = None) -> SyncResult:
        from nook.db import now

        res, started = SyncResult(sid), now()
        adapter = self.adapters.get(sid)
        if adapter is None:
            res.status, res.error = "failed", "source disabled"
            return res
        try:
            drafts = await adapter.fetch_feed(FeedOptions(limit=limit, kind=kind, tag=tag))
        except SourceError as e:
            self.db.set_source_status(sid, e.status, str(e))
            res.status, res.error = "failed", str(e)
        except Exception as e:  # never let one source take the others down
            self.db.set_source_status(sid, "unknown_error", type(e).__name__)
            res.status, res.error = "failed", f"{type(e).__name__}: {e}"
        else:
            res.fetched = len(drafts)
            for d in drafts:
                try:
                    _, inserted = self.db.upsert(d)
                    res.inserted += inserted
                    res.updated += not inserted
                except Exception as e:
                    res.status, res.error = "partial", f"{type(e).__name__}: {e}"
            self.db.set_source_status(sid, "enabled", res.error, synced=True)
        self.db.record_sync(sid, started, res.status, res.fetched, res.inserted, res.updated, res.error)
        return res

    async def sync(self, sources: list[str] | None = None, limit: int | None = None, metadata_only: bool = False,
                   download_missing: bool = False, force: bool = False, on_result=None) -> list[SyncResult]:
        limit = limit or self.cfg.default_limit
        sids = sources or list(self.adapters)
        results = await asyncio.gather(*(self.sync_source(s, limit) for s in sids))
        if on_result:
            for r in results:
                on_result(r)
        if not metadata_only:
            # newly discovered articles only, bounded; --download-content widens to everything missing
            rows = self.db.list(limit=10_000, missing_content=True, dedupe=False)
            rows = [r for r in rows if r["source_id"] in sids]
            cap = len(rows) if download_missing else self.cfg.max_auto_download
            by_src = {r.source_id: r for r in results}
            for row in await self.download_many([r["id"] for r in rows[:cap]], force=force):
                if row[1] and row[0] in by_src:
                    by_src[row[0]].downloaded += 1
        return list(results)

    # ---- content -------------------------------------------------------
    async def ensure_content(self, aid: int, force: bool = False) -> tuple[str, str | None]:
        """Return (status, error). Never deletes an existing cached body on failure."""
        a = self.db.get(aid)
        if a is None:
            return "failed", "no such article"
        if a["content_markdown"] and not force:
            return "available", None
        try:
            adapter = self.adapters.get(a["source_id"])
            body = None
            if adapter and a["external_id"] and a["source_id"] == "devto":
                try:
                    body = await adapter.fetch_content(a["external_id"])
                except SourceError:
                    body = None
            if body:
                body = sanitize(body)
            else:
                body = await extract_url(a["canonical_url"])
            self.db.save_content(aid, body)
            return "available", None
        except ExtractionError as e:
            self.db.mark_content_failed(aid, e.status, str(e))
            return e.status, str(e)

    async def download_many(self, ids: list[int], force: bool = False) -> list[tuple[str, bool]]:
        sem = asyncio.Semaphore(self.cfg.max_concurrent_downloads)

        async def one(aid: int):
            async with sem:
                a = self.db.get(aid)
                status, _ = await self.ensure_content(aid, force)
                return a["source_id"], status == "available"

        return list(await asyncio.gather(*(one(i) for i in ids)))
