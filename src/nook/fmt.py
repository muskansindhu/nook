from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from rich.markup import escape
from rich.table import Table
from rich.text import Text

from nook.constants import MASCOT_PALETTE, MASCOT_PIXELS, SOURCE_LABELS



def rel_time(iso: str | None) -> str:
    if not iso:
        return "—"
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    s = int((datetime.now(timezone.utc) - dt).total_seconds())
    if s < 3600:
        return f"{max(s // 60, 1)}m ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    return f"{s // 86400}d ago"


def meta_line(a: sqlite3.Row) -> str:
    bits = [SOURCE_LABELS.get(a["source_id"], a["source_id"])]
    if a["author"]:
        bits.append(a["author"])
    bits.append(rel_time(a["published_at"] or a["fetched_at"]))
    if a["score"] is not None:
        bits.append(f"{a['score']} pts")
    if a["comment_count"] is not None:
        bits.append(f"{a['comment_count']} comments")
    return " · ".join(bits)


def flags(a: sqlite3.Row) -> str:
    return ("★" if a["is_bookmarked"] else " ") + ("✓" if a["is_read"] else "•") + ("▣" if a["content_markdown"] else "▢")


def tags(a: sqlite3.Row) -> list[str]:
    return json.loads(a["tags_json"] or "[]")


def article_table(rows: list[sqlite3.Row], title: str | None = None) -> Table:
    t = Table(title=title, title_justify="left", show_lines=False, header_style="bold")
    t.add_column("ID", justify="right", style="cyan")
    t.add_column("", no_wrap=True)
    t.add_column("Title", overflow="fold", ratio=3)
    t.add_column("Info", style="dim", overflow="fold", ratio=2)
    for a in rows:
        t.add_row(str(a["id"]), flags(a), escape(a["title"]), escape(meta_line(a)))
    return t


def render_mascot() -> Text:
    """Pixel grid -> half-block art (each text row shows two pixel rows)."""
    out = Text(justify="center")
    rows = MASCOT_PIXELS
    for y in range(0, len(rows), 2):
        top = rows[y]
        bottom = rows[y + 1] if y + 1 < len(rows) else "." * len(top)
        for tp, bt in zip(top, bottom):
            tc, bc = MASCOT_PALETTE.get(tp), MASCOT_PALETTE.get(bt)
            if tc and bc:
                out.append("█" if tc == bc else "▀", style=tc if tc == bc else f"{tc} on {bc}")
            elif tc:
                out.append("▀", style=tc)
            elif bc:
                out.append("▄", style=bc)
            else:
                out.append(" ")
        out.append("\n")
    return out
