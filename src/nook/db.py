from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nook.constants import ARTICLE_VIEW_SELECT, SCHEMA, SOURCE_NAMES
from nook.models import ArticleDraft




def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _strip_markdown(md: str) -> str:
    return re.sub(r"[#>*`_\[\]]", "", md)


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.init()

    def init(self) -> None:
        with self.conn:
            self.conn.executescript(SCHEMA)
            for sid, name in SOURCE_NAMES.items():
                self.conn.execute("INSERT OR IGNORE INTO sources(id, name) VALUES (?, ?)", (sid, name))
        try:
            with self.conn:
                self.conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5"
                    "(title, description, tags, content)"
                )
            self.has_fts = True
        except sqlite3.OperationalError:
            self.has_fts = False

    def close(self) -> None:
        self.conn.close()

    # ---- sources -------------------------------------------------------
    def set_source_status(self, sid: str, status: str, error: str | None = None, synced: bool = False) -> None:
        with self.conn:
            if synced:
                self.conn.execute(
                    "UPDATE sources SET status=?, last_error=?, last_synced_at=? WHERE id=?",
                    (status, error, now(), sid),
                )
            else:
                self.conn.execute("UPDATE sources SET status=?, last_error=? WHERE id=?", (status, error, sid))

    def sources(self) -> list[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM sources ORDER BY rowid").fetchall()

    def record_sync(self, sid: str, started: str, status: str, fetched: int, ins: int, upd: int, err: str | None):
        with self.conn:
            self.conn.execute(
                "INSERT INTO sync_runs(source_id,started_at,finished_at,status,fetched_count,inserted_count,"
                "updated_count,error_message) VALUES (?,?,?,?,?,?,?,?)",
                (sid, started, now(), status, fetched, ins, upd, err),
            )

    # ---- articles ------------------------------------------------------
    def upsert(self, d: ArticleDraft) -> tuple[int, bool]:
        """Insert or update by (source, external_id) or (source, url). Returns (id, inserted)."""
        row = None
        if d.external_id:
            row = self.conn.execute(
                "SELECT id FROM articles WHERE source_id=? AND external_id=?", (d.source_id, d.external_id)
            ).fetchone()
        if row is None:
            row = self.conn.execute(
                "SELECT id FROM articles WHERE source_id=? AND canonical_url=?", (d.source_id, d.canonical_url)
            ).fetchone()
        ts, pub = now(), d.published_at.isoformat() if d.published_at else None
        vals = (
            d.external_id, d.canonical_url, d.title, d.author, d.description, pub, ts,
            json.dumps(d.tags), d.score, d.comment_count, d.reading_time_minutes,
            json.dumps(d.metadata, default=str), ts,
        )
        with self.conn:
            if row:
                aid = row["id"]
                self.conn.execute(
                    "UPDATE articles SET external_id=?, canonical_url=?, title=?, author=?, description=?,"
                    "published_at=COALESCE(?, published_at), fetched_at=?, tags_json=?, score=?, comment_count=?,"
                    "reading_time_minutes=COALESCE(?, reading_time_minutes), source_metadata_json=?, updated_at=?"
                    " WHERE id=?",
                    (*vals, aid),
                )
                inserted = False
            else:
                cur = self.conn.execute(
                    "INSERT INTO articles(source_id, external_id, canonical_url, title, author, description,"
                    "published_at, fetched_at, tags_json, score, comment_count, reading_time_minutes,"
                    "source_metadata_json, updated_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (d.source_id, *vals, ts),
                )
                aid, inserted = cur.lastrowid, True
                self.conn.execute("INSERT OR IGNORE INTO user_article_state(article_id, updated_at) VALUES (?,?)", (aid, ts))
            if d.content_markdown:
                self._store_content(aid, d.content_markdown)
            else:
                self._reindex(aid)
        return aid, inserted

    def _store_content(self, aid: int, markdown: str) -> None:
        ts = now()
        self.conn.execute(
            "UPDATE articles SET content_markdown=?, content_text=?, content_status='available',"
            "content_error=NULL, content_fetched_at=?, updated_at=? WHERE id=?",
            (markdown, _strip_markdown(markdown), ts, ts, aid),
        )
        self._reindex(aid)

    def save_content(self, aid: int, markdown: str) -> None:
        with self.conn:
            self._store_content(aid, markdown)

    def mark_content_failed(self, aid: int, status: str, error: str) -> None:
        """Failed extraction never deletes an older cached copy."""
        with self.conn:
            self.conn.execute(
                "UPDATE articles SET content_status = CASE WHEN content_markdown IS NOT NULL "
                "THEN content_status ELSE ? END, content_error=?, updated_at=? WHERE id=?",
                (status, error, now(), aid),
            )

    def set_description_if_empty(self, aid: int, text: str) -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE articles SET description=? WHERE id=? AND (description IS NULL OR description='')", (text, aid)
            )
            self._reindex(aid)

    def _reindex(self, aid: int) -> None:
        if not self.has_fts:
            return
        r = self.conn.execute(
            "SELECT title, description, tags_json, content_text FROM articles WHERE id=?", (aid,)
        ).fetchone()
        self.conn.execute("DELETE FROM articles_fts WHERE rowid=?", (aid,))
        tags = " ".join(json.loads(r["tags_json"]))
        self.conn.execute(
            "INSERT INTO articles_fts(rowid,title,description,tags,content) VALUES (?,?,?,?,?)",
            (aid, r["title"], r["description"] or "", tags, r["content_text"] or ""),
        )

    def get(self, aid: int) -> sqlite3.Row | None:
        return self.conn.execute(ARTICLE_VIEW_SELECT + " WHERE a.id=?", (aid,)).fetchone()

    def list(
        self, source: str | None = None, limit: int = 30, offset: int = 0, unread: bool = False,
        bookmarked: bool = False, history: bool = False, missing_content: bool = False,
        sort: str = "newest", dedupe: bool = True,
    ) -> list[sqlite3.Row]:
        where, args = [], []
        if source:
            where.append("a.source_id=?"); args.append(source)
        elif dedupe:  # unified feed: collapse identical canonical URLs across sources
            where.append("a.id = (SELECT MIN(b.id) FROM articles b WHERE b.canonical_url = a.canonical_url)")
        if unread:
            where.append("COALESCE(s.is_read,0)=0")
        if bookmarked:
            where.append("s.is_bookmarked=1")
        if history:
            where.append("s.last_opened_at IS NOT NULL")
        if missing_content:
            where.append("a.content_markdown IS NULL")
        order = {
            "newest": "COALESCE(a.published_at, a.fetched_at) DESC",
            "discussed": "COALESCE(a.comment_count,0) DESC",
            "popular": "COALESCE(a.score,0) DESC",
        }[sort]
        if history:
            order = "s.last_opened_at DESC"
        sql = ARTICLE_VIEW_SELECT + (" WHERE " + " AND ".join(where) if where else "")
        sql += f" ORDER BY {order}, a.id DESC LIMIT ? OFFSET ?"
        return self.conn.execute(sql, (*args, limit, offset)).fetchall()

    def search(self, q: str, source: str | None = None, unread: bool = False, bookmarked: bool = False,
               limit: int = 30) -> list[sqlite3.Row]:
        where, args = [], []
        if source:
            where.append("a.source_id=?"); args.append(source)
        if unread:
            where.append("COALESCE(s.is_read,0)=0")
        if bookmarked:
            where.append("s.is_bookmarked=1")
        extra = (" AND " + " AND ".join(where)) if where else ""
        if self.has_fts:
            terms = " ".join(f'"{t}"' for t in re.findall(r"\w+", q))
            if not terms:
                return []
            sql = (ARTICLE_VIEW_SELECT + " WHERE a.id IN (SELECT rowid FROM articles_fts WHERE articles_fts MATCH ?)"
                   + extra + " ORDER BY COALESCE(a.published_at,a.fetched_at) DESC LIMIT ?")
            return self.conn.execute(sql, (terms, *args, limit)).fetchall()
        like = f"%{q}%"
        sql = (ARTICLE_VIEW_SELECT + " WHERE (a.title LIKE ? OR a.description LIKE ? OR a.content_text LIKE ?)"
               + extra + " ORDER BY COALESCE(a.published_at,a.fetched_at) DESC LIMIT ?")
        return self.conn.execute(sql, (like, like, like, *args, limit)).fetchall()

    # ---- user state ----------------------------------------------------
    def _state(self, aid: int, **cols: Any) -> None:
        sets = ", ".join(f"{k}=?" for k in cols)
        with self.conn:
            self.conn.execute("INSERT OR IGNORE INTO user_article_state(article_id, updated_at) VALUES (?,?)", (aid, now()))
            self.conn.execute(f"UPDATE user_article_state SET {sets}, updated_at=? WHERE article_id=?", (*cols.values(), now(), aid))

    def set_bookmark(self, aid: int, value: bool) -> None:
        self._state(aid, is_bookmarked=int(value))

    def set_read(self, aid: int, value: bool) -> None:
        self._state(aid, is_read=int(value), **({} if value else {"read_progress": 0.0}))

    def set_progress(self, aid: int, progress: float) -> None:
        self._state(aid, read_progress=max(0.0, min(1.0, progress)))

    def touch_opened(self, aid: int) -> None:
        ts = now()
        self._state(aid, last_opened_at=ts)
        with self.conn:
            self.conn.execute("UPDATE user_article_state SET first_opened_at=COALESCE(first_opened_at, ?) WHERE article_id=?", (ts, aid))

    def cache_stats(self) -> dict[str, int]:
        rows = self.conn.execute("SELECT content_status, COUNT(*) c FROM articles GROUP BY content_status").fetchall()
        stats = {r["content_status"]: r["c"] for r in rows}
        stats["total"] = sum(stats.values())
        return stats
