"""The Daily Diff (tdd.cat). Uses the site's advertised JSON feed (<link rel=alternate type=application/json>)."""
from __future__ import annotations

from datetime import datetime, timezone

from nook.adapters.base import get_json, make_client
from nook.models import ArticleDraft, FeedOptions, SourceError
from nook.urls import normalize_url

FEED_URL = "https://tdd.cat/json"


class DailyDiff:
    source_id = "tdd"
    display_name = "The Daily Diff"

    async def fetch_feed(self, options: FeedOptions) -> list[ArticleDraft]:
        async with make_client() as client:
            data = await get_json(client, FEED_URL)
        if not isinstance(data, dict) or not isinstance(data.get("stories"), list):
            raise SourceError("parse_error", "tdd.cat feed shape changed (no 'stories' list)")
        out = []
        for s in data["stories"]:
            d = self._normalize(s, data.get("date"))
            if d:
                out.append(d)
        return out[: options.limit]

    @staticmethod
    def _normalize(s: dict, edition: str | None) -> ArticleDraft | None:
        if not isinstance(s, dict) or not s.get("url") or not s.get("title"):
            return None
        date = s.get("date") or edition
        try:
            published = datetime.fromisoformat(date).replace(tzinfo=timezone.utc) if date else None
        except ValueError:
            published = None
        authors = s.get("authors") or []
        why, body = s.get("why_read"), s.get("content")
        md = None
        if body:
            md = (f"> **Why read:** {why}\n\n" if why else "") + body
        return ArticleDraft(
            source_id="tdd", external_id=str(s.get("hn_id")) if s.get("hn_id") else None,
            canonical_url=normalize_url(s["url"]), title=s["title"],
            author=", ".join(authors) if isinstance(authors, list) and authors else None,
            description=why, published_at=published, tags=[s["source"]] if s.get("source") else [],
            content_markdown=md,
            metadata={"edition": edition, "discussion": s.get("comments"), "origin": s.get("source")},
        )

    async def fetch_content(self, external_id: str) -> str | None:
        return None
