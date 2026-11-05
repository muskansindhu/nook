from __future__ import annotations

from nook.adapters.base import get_json, make_client, parse_dt, safe_normalize
from nook.constants import DEVTO_BASE, DEVTO_HEADERS, DEVTO_MAX_PER_PAGE, DEVTO_TOP_DAYS
from nook.models import ArticleDraft, FeedOptions, SourceError
from nook.urls import normalize_url



class DevTo:
    source_id = "devto"
    display_name = "DEV Community"

    async def fetch_feed(self, options: FeedOptions) -> list[ArticleDraft]:
        kind = options.kind or "latest"
        params: dict = {"per_page": min(options.limit, DEVTO_MAX_PER_PAGE)}
        path = "/articles"
        if kind == "latest":
            path = "/articles/latest"
        elif kind == "top":
            params["top"] = DEVTO_TOP_DAYS
        elif kind != "popular":
            raise SourceError("unknown_error", f"unknown DEV feed '{kind}' (use: latest, top, popular)")
        if options.tag:
            params["tag"] = options.tag
        async with make_client(headers=DEVTO_HEADERS) as client:
            data = await get_json(client, DEVTO_BASE + path, params=params)
        if not isinstance(data, list):
            raise SourceError("parse_error", "unexpected DEV response")
        out = []
        for a in data:
            if d := safe_normalize(self._normalize, a):
                out.append(d)
        return out

    @staticmethod
    def _normalize(a: dict) -> ArticleDraft:
        tags = a.get("tag_list") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(",") if t.strip()]
        return ArticleDraft(
            source_id="devto", external_id=str(a["id"]), canonical_url=normalize_url(a["url"]),
            title=a["title"], author=(a.get("user") or {}).get("name"),
            description=a.get("description"), published_at=parse_dt(a.get("published_timestamp")),
            tags=tags, score=a.get("public_reactions_count"), comment_count=a.get("comments_count"),
            reading_time_minutes=a.get("reading_time_minutes"),
        )

    async def fetch_content(self, external_id: str) -> str | None:
        async with make_client(headers=DEVTO_HEADERS) as client:
            data = await get_json(client, f"{DEVTO_BASE}/articles/{external_id}")
        body = data.get("body_markdown") if isinstance(data, dict) else None
        return body or None
