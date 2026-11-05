from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Protocol

import httpx

from nook.constants import HTTP_CONNECT_TIMEOUT_S, HTTP_TIMEOUT_S, USER_AGENT
from nook.models import ArticleDraft, FeedOptions, SourceError


class SourceAdapter(Protocol):
    source_id: str
    display_name: str

    async def fetch_feed(self, options: FeedOptions) -> list[ArticleDraft]: ...

    async def fetch_content(self, draft_external_id: str) -> str | None:
        """Return markdown body if the source supplies one, else None (use the extractor)."""
        ...


def make_client(**kw) -> httpx.AsyncClient:
    headers = {"User-Agent": USER_AGENT, **kw.pop("headers", {})}
    return httpx.AsyncClient(timeout=httpx.Timeout(HTTP_TIMEOUT_S, connect=HTTP_CONNECT_TIMEOUT_S), headers=headers, follow_redirects=True, **kw)


def safe_normalize(fn: Callable[..., ArticleDraft | None], *args) -> ArticleDraft | None:
    """Run an adapter's normalizer; skip malformed items (incl. pydantic ValidationError) instead of failing the source."""
    try:
        return fn(*args)
    except (KeyError, TypeError, ValueError):
        return None


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def get_json(client: httpx.AsyncClient, url: str, **kw):
    """GET JSON, translating transport/HTTP failures into SourceError with a status."""
    try:
        r = await client.get(url, **kw)
    except httpx.TransportError as e:
        raise SourceError("temporarily_unavailable", f"network error: {type(e).__name__}") from e
    if r.status_code == 429:
        raise SourceError("rate_limited", f"rate limited (retry-after {r.headers.get('retry-after', '?')}s)")
    if r.status_code in (401, 403):
        raise SourceError("needs_auth", f"HTTP {r.status_code}: authentication failed")
    if r.status_code >= 500:
        raise SourceError("temporarily_unavailable", f"HTTP {r.status_code}")
    if r.status_code >= 400:
        raise SourceError("unknown_error", f"HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError as e:
        raise SourceError("parse_error", "response was not valid JSON") from e
