from __future__ import annotations

from nook.adapters.base import get_json, make_client, parse_dt
from nook.models import ArticleDraft, FeedOptions, SourceError
from nook.urls import normalize_url

BASE = "https://dev.to/api"
HEADERS = {"Accept": "application/vnd.forem.api-v1+json"}


class DevTo:
    source_id = "devto"
    display_name = "DEV Community"

    async def fetch_feed(self, options: FeedOptions) -> list[ArticleDraft]:
        kind = options.kind or "latest"
        params: dict = {"per_page": min(options.limit, 100)}
        path = "/articles"
        if kind == "latest":
            path = "/articles/latest"
        elif kind == "top":
            params["top"] = 7
        elif kind != "popular":
            raise SourceError("unknown_error", f"unknown DEV feed '{kind}' (use: latest, top, popular)")
        if options.tag:
            params["tag"] = options.tag
        async with make_client(headers=HEADERS) as client:
            data = await get_json(client, BASE + path, params=params)
        if not isinstance(data, list):
            raise SourceError("parse_error", "unexpected DEV response")
        out = []
        for a in data:
            try:
                out.append(self._normalize(a))
            except (KeyError, TypeError):
                continue  # skip malformed entries rather than failing the source
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
        async with make_client(headers=HEADERS) as client:
            data = await get_json(client, f"{BASE}/articles/{external_id}")
        body = data.get("body_markdown") if isinstance(data, dict) else None
        return body or None
