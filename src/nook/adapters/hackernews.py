from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from nook.adapters.base import get_json, make_client
from nook.constants import HN_BASE, HN_FEEDS, HN_FETCH_CONCURRENCY, HN_OVERFETCH
from nook.extraction import html_fragment_to_markdown
from nook.models import ArticleDraft, FeedOptions, SourceError
from nook.urls import normalize_url


class HackerNews:
    source_id = "hn"
    display_name = "Hacker News"

    async def fetch_feed(self, options: FeedOptions) -> list[ArticleDraft]:
        kind = options.kind or "top"
        if kind not in HN_FEEDS:
            raise SourceError("unknown_error", f"unknown HN feed '{kind}' (use: {', '.join(HN_FEEDS)})")
        async with make_client() as client:
            ids = await get_json(client, f"{HN_BASE}/{HN_FEEDS[kind]}.json")
            if not isinstance(ids, list):
                raise SourceError("parse_error", "unexpected HN id list")
            sem = asyncio.Semaphore(HN_FETCH_CONCURRENCY)

            async def item(i: int):
                async with sem:
                    try:
                        return await get_json(client, f"{HN_BASE}/item/{i}.json")
                    except SourceError:
                        return None

            # over-fetch a little: deleted/dead/non-story items get dropped
            items = await asyncio.gather(*(item(i) for i in ids[: options.limit + HN_OVERFETCH]))
        drafts = [d for it in items if (d := self._normalize(it, kind))]
        return drafts[: options.limit]

    @staticmethod
    def _normalize(it: dict | None, kind: str) -> ArticleDraft | None:
        if not it or it.get("deleted") or it.get("dead") or it.get("type") != "story" or not it.get("title"):
            return None
        hn_url = f"https://news.ycombinator.com/item?id={it['id']}"
        url = it.get("url") or hn_url
        ts = it.get("time")
        return ArticleDraft(
            source_id="hn", external_id=str(it["id"]), canonical_url=normalize_url(url),
            title=it["title"], author=it.get("by"),
            content_markdown=html_fragment_to_markdown(it["text"]) if not it.get("url") and it.get("text") else None,
            published_at=datetime.fromtimestamp(ts, timezone.utc) if ts else None,
            score=it.get("score"), comment_count=it.get("descendants"),
            tags=[kind] if kind in ("ask", "show") else [],
            metadata={"hn_url": hn_url, "feed": kind},
        )

    async def fetch_content(self, external_id: str) -> str | None:
        return None  # story body is the linked page; shared extractor handles it
