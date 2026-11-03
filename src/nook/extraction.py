from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx
import trafilatura

from nook.adapters.base import USER_AGENT
from nook.urls import is_safe_url

MAX_BYTES = 3_000_000
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)")


class ExtractionError(Exception):
    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status  # failed / blocked / unavailable


def sanitize(text: str) -> str:
    """Strip ANSI escapes and control characters from untrusted article content."""
    return _CONTROL.sub("", _ANSI.sub("", text)).replace("\r\n", "\n")


async def fetch_html(url: str) -> str:
    """Safe GET: http(s) only, no private hosts (re-checked on every redirect), size-capped."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=8.0), headers={"User-Agent": USER_AGENT}, follow_redirects=False
    ) as client:
        for _ in range(5):
            if not is_safe_url(url):
                raise ExtractionError("blocked", "refusing to fetch non-public or non-http(s) URL")
            try:
                async with client.stream("GET", url) as r:
                    if r.status_code in (301, 302, 303, 307, 308) and r.headers.get("location"):
                        url = urljoin(url, r.headers["location"])
                        continue
                    if r.status_code in (401, 402, 403, 429):
                        raise ExtractionError("blocked", f"site denied access (HTTP {r.status_code})")
                    if r.status_code >= 400:
                        raise ExtractionError("failed", f"HTTP {r.status_code}")
                    ctype = r.headers.get("content-type", "")
                    if "html" not in ctype and "xml" not in ctype and "text" not in ctype:
                        raise ExtractionError("unavailable", f"not an HTML page ({ctype or 'unknown type'})")
                    buf = bytearray()
                    async for chunk in r.aiter_bytes():
                        buf += chunk
                        if len(buf) > MAX_BYTES:
                            break
                    return bytes(buf).decode(r.encoding or "utf-8", errors="replace")
            except httpx.TransportError as e:
                raise ExtractionError("failed", f"network error: {type(e).__name__}") from e
        raise ExtractionError("failed", "too many redirects")


def extract_markdown(html: str, url: str | None = None) -> str:
    md = trafilatura.extract(
        html, url=url, output_format="markdown", include_links=True,
        include_formatting=True, include_tables=True, favor_recall=True,
    )
    if not md or len(md.strip()) < 200:
        raise ExtractionError("unavailable", "no readable article content found (page may need JavaScript)")
    return sanitize(md)


async def extract_url(url: str) -> str:
    return extract_markdown(await fetch_html(url), url)
