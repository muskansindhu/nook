from __future__ import annotations

from nook.adapters.base import get_json, make_client, parse_dt
from nook.constants import DAILYDEV_BASE, DAILYDEV_MAX_PAGE
from nook.models import ArticleDraft, FeedOptions, SourceError
from nook.urls import normalize_url



class DailyDev:
    source_id = "dailydev"
    display_name = "daily.dev"

    def __init__(self, token: str | None):
        self._token = token

    async def fetch_feed(self, options: FeedOptions) -> list[ArticleDraft]:
        if not self._token:
            raise SourceError("needs_auth", "set DAILY_DEV_TOKEN (create one at https://daily.dev/settings/api)")
        out: list[ArticleDraft] = []
        cursor = None
        async with make_client(headers={"Authorization": f"Bearer {self._token}"}) as client:
            while len(out) < options.limit:
                params = {"limit": min(DAILYDEV_MAX_PAGE, options.limit - len(out))}
                if cursor:
                    params["cursor"] = cursor
                data = await get_json(client, f"{DAILYDEV_BASE}/feeds/foryou", params=params)
                if not isinstance(data, dict) or not isinstance(data.get("data"), list):
                    raise SourceError("parse_error", "unexpected daily.dev response shape")
                for p in data["data"]:
                    d = self._normalize(p)
                    if d:
                        out.append(d)
                page = data.get("pagination") or {}
                cursor = page.get("cursor")
                if not page.get("hasNextPage") or not cursor:
                    break
        return out[: options.limit]

    @staticmethod
    def _normalize(p: dict) -> ArticleDraft | None:
        if not isinstance(p, dict) or not p.get("url") or not p.get("title"):
            return None
        author = p.get("author") if isinstance(p.get("author"), dict) else {}
        source = p.get("source") if isinstance(p.get("source"), dict) else {}
        return ArticleDraft(
            source_id="dailydev", external_id=str(p.get("id")) if p.get("id") else None,
            canonical_url=normalize_url(p["url"]), title=p["title"],
            author=author.get("name") or author.get("username") or source.get("name"),
            description=p.get("summary"), published_at=parse_dt(p.get("publishedAt") or p.get("createdAt")),
            tags=[t for t in (p.get("tags") or []) if isinstance(t, str)],
            score=p.get("numUpvotes"), comment_count=p.get("numComments"), reading_time_minutes=p.get("readTime"),
            metadata={"comments_url": p.get("commentsPermalink"), "origin": source.get("name")},
        )

    async def fetch_content(self, external_id: str) -> str | None:
        return None
