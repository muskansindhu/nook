from __future__ import annotations

from urllib.parse import urljoin

import httpx
import trafilatura
from bs4 import BeautifulSoup

from nook.constants import (
    ANSI_RE, CONTROL_CHARS_RE, EXTRACT_TIMEOUT_S, HTTP_CONNECT_TIMEOUT_S, MAX_REDIRECTS,
    MAX_RESPONSE_BYTES, MIN_ARTICLE_CHARS, USER_AGENT,
)
from nook.urls import is_safe_url



class ExtractionError(Exception):
    def __init__(self, status: str, message: str, summary: str | None = None):
        super().__init__(message)
        self.status = status  # failed / blocked / unavailable
        self.summary = summary  # page <meta description>, when the body itself couldn't be read


def sanitize(text: str) -> str:
    """Strip ANSI escapes and control characters from untrusted article content."""
    return CONTROL_CHARS_RE.sub("", ANSI_RE.sub("", text)).replace("\r\n", "\n")


async def fetch_html(url: str) -> str:
    """Safe GET: http(s) only, no private hosts (re-checked on every redirect), size-capped."""
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(EXTRACT_TIMEOUT_S, connect=HTTP_CONNECT_TIMEOUT_S), headers={"User-Agent": USER_AGENT}, follow_redirects=False
    ) as client:
        for _ in range(MAX_REDIRECTS):
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
                        if len(buf) > MAX_RESPONSE_BYTES:
                            break
                    return bytes(buf).decode(r.encoding or "utf-8", errors="replace")
            except httpx.TransportError as e:
                raise ExtractionError("failed", f"network error: {type(e).__name__}") from e
        raise ExtractionError("failed", "too many redirects")


def page_summary(html: str) -> str | None:
    """The page's own description (og:description / meta description), if any."""
    soup = BeautifulSoup(html, "html.parser")
    for attrs in ({"property": "og:description"}, {"name": "description"}, {"name": "twitter:description"}):
        tag = soup.find("meta", attrs=attrs)
        if tag and tag.get("content", "").strip():
            return sanitize(tag["content"].strip())
    return None


def html_fragment_to_markdown(fragment: str) -> str:
    """Convert a small HTML snippet (e.g. an HN post body) into readable markdown."""
    soup = BeautifulSoup(fragment, "html.parser")
    for a in soup.find_all("a"):
        a.replace_with(f"[{a.get_text()}]({a.get('href', '')})")
    for pre in soup.find_all("pre"):
        pre.replace_with(f"\n\n```\n{pre.get_text()}\n```\n\n")
    for p in soup.find_all("p"):
        p.insert_before("\n\n")
    return sanitize(soup.get_text()).strip()


def extract_markdown(html: str, url: str | None = None) -> str:
    md = trafilatura.extract(
        html, url=url, output_format="markdown", include_links=True,
        include_formatting=True, include_tables=True, favor_recall=True,
    )
    if not md or len(md.strip()) < MIN_ARTICLE_CHARS:
        raise ExtractionError(
            "unavailable", "no readable article content found (page may need JavaScript)", page_summary(html)
        )
    return sanitize(md)


async def extract_url(url: str) -> str:
    return extract_markdown(await fetch_html(url), url)
