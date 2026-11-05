"""All module-level constants for nook live here."""
from __future__ import annotations

import re

from nook import __version__

# ---- sources ---------------------------------------------------------------
SOURCE_IDS = ("hn", "tdd", "devto", "dailydev")
SOURCE_NAMES = {
    "hn": "Hacker News",
    "tdd": "The Daily Diff",
    "devto": "DEV Community",
    "dailydev": "daily.dev",
}
SOURCE_LABELS = {"hn": "HN", "tdd": "TDD", "devto": "DEV", "dailydev": "daily.dev"}

# ---- app defaults ------------------------------------------------------------
APP_NAME = "nook"
DEFAULT_LIMIT = 30
DEFAULT_MAX_AUTO_DOWNLOAD = 25
DEFAULT_MAX_CONCURRENT_DOWNLOADS = 4
SYNC_UNBOUNDED_LIMIT = 10_000  # "all rows" for internal list queries
TUI_PAGE_SIZE = 200  # bounded list, never render an unbounded feed
TUI_VIEWS = [
    ("all", "All articles"), ("hn", "Hacker News"), ("tdd", "The Daily Diff"), ("devto", "DEV Community"),
    ("dailydev", "daily.dev"), ("bookmarks", "★ Bookmarks"), ("unread", "Unread"), ("history", "Recently read"),
]

# ---- HTTP --------------------------------------------------------------------
USER_AGENT = f"nook/{__version__} (personal terminal reader)"
HTTP_TIMEOUT_S = 15.0
HTTP_CONNECT_TIMEOUT_S = 8.0
EXTRACT_TIMEOUT_S = 20.0
DOCTOR_TIMEOUT_S = 8
MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 3_000_000
MIN_ARTICLE_CHARS = 200
HN_FETCH_CONCURRENCY = 8
HN_OVERFETCH = 10  # deleted/dead/non-story items get dropped

# ---- source endpoints --------------------------------------------------------
HN_BASE = "https://hacker-news.firebaseio.com/v0"
HN_FEEDS = {"top": "topstories", "new": "newstories", "best": "beststories",
            "ask": "askstories", "show": "showstories"}
DEVTO_BASE = "https://dev.to/api"
DEVTO_HEADERS = {"Accept": "application/vnd.forem.api-v1+json"}
DEVTO_MAX_PER_PAGE = 100
DEVTO_TOP_DAYS = 7
DAILYDEV_BASE = "https://api.daily.dev/public/v1"
DAILYDEV_MAX_PAGE = 50
TDD_FEED_URL = "https://tdd.cat/json"
DOCTOR_URLS = {
    "hn": f"{HN_BASE}/maxitem.json",
    "tdd": TDD_FEED_URL,
    "devto": f"{DEVTO_BASE}/articles?per_page=1",
    "dailydev": f"{DAILYDEV_BASE}/skill.md",
}

# ---- reader fallback messages (when no article body could be cached) --------
FALLBACK_MESSAGES = {
    "unavailable": "nook can't read this page in the terminal: it has no readable text (it likely needs JavaScript).",
    "blocked": "The site blocked automated access, so the article couldn't be downloaded.",
    "failed": "Downloading the article failed. Press R (or run `nook cache download ID`) to retry.",
    "pending": "This article hasn't been downloaded yet.",
}
DISCUSSION_METADATA_KEYS = ("hn_url", "discussion", "comments_url")  # where adapters stash a discussion link

# ---- URL / content sanitizing ------------------------------------------------
TRACKING_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid", "ref", "ref_src", "igshid"}
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07]*(?:\x07|\x1b\\)")

# ---- config file -------------------------------------------------------------
DEFAULT_TOML = """\
[app]
default_limit = 30
auto_mark_read = true

[cache]
max_auto_download_per_sync = 25
max_concurrent_downloads = 4

[sources.hn]
enabled = true
[sources.tdd]
enabled = true
[sources.devto]
enabled = true
[sources.dailydev]
enabled = true
# Token comes from the DAILY_DEV_TOKEN environment variable, never this file.
"""

# ---- database ----------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
  last_synced_at TEXT, last_error TEXT, status TEXT NOT NULL DEFAULT 'enabled'
);
CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id TEXT NOT NULL REFERENCES sources(id),
  external_id TEXT, canonical_url TEXT NOT NULL, title TEXT NOT NULL,
  author TEXT, description TEXT, published_at TEXT, fetched_at TEXT NOT NULL,
  tags_json TEXT NOT NULL DEFAULT '[]', score INTEGER, comment_count INTEGER,
  reading_time_minutes INTEGER, content_markdown TEXT, content_text TEXT,
  content_status TEXT NOT NULL DEFAULT 'pending', content_error TEXT,
  content_fetched_at TEXT, source_metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_art_ext ON articles(source_id, external_id) WHERE external_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_art_url ON articles(source_id, canonical_url);
CREATE INDEX IF NOT EXISTS ix_art_pub ON articles(source_id, published_at);
CREATE INDEX IF NOT EXISTS ix_art_status ON articles(content_status);
CREATE TABLE IF NOT EXISTS user_article_state (
  article_id INTEGER PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
  is_bookmarked INTEGER NOT NULL DEFAULT 0, is_read INTEGER NOT NULL DEFAULT 0,
  read_progress REAL NOT NULL DEFAULT 0, first_opened_at TEXT, last_opened_at TEXT,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_state_bm ON user_article_state(is_bookmarked);
CREATE INDEX IF NOT EXISTS ix_state_read ON user_article_state(is_read);
CREATE INDEX IF NOT EXISTS ix_state_last ON user_article_state(last_opened_at);
CREATE TABLE IF NOT EXISTS sync_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, source_id TEXT NOT NULL, started_at TEXT NOT NULL,
  finished_at TEXT, status TEXT NOT NULL, fetched_count INTEGER DEFAULT 0,
  inserted_count INTEGER DEFAULT 0, updated_count INTEGER DEFAULT 0, error_message TEXT
);
"""

ARTICLE_VIEW_SELECT = """
SELECT a.*, COALESCE(s.is_bookmarked,0) AS is_bookmarked, COALESCE(s.is_read,0) AS is_read,
       COALESCE(s.read_progress,0) AS read_progress, s.last_opened_at AS last_opened_at
FROM articles a LEFT JOIN user_article_state s ON s.article_id = a.id
"""

# ---- mascot ------------------------------------------------------------------
# "Nooky", a pixel-art bookworm. One char per pixel, drawn two pixel rows per text row with half-blocks.
MASCOT_PALETTE = {
    "g": "#8be28b",  # body
    "d": "#4fb36b",  # mouth / shade
    "k": "#23263a",  # eyes
    "w": "#ffffff",  # eye shine
    "p": "#ff9db5",  # cheeks
    "c": "#f6ecd2",  # book pages
    "b": "#c9803c",  # book cover
}
MASCOT_PIXELS = [
    "..g......g..",
    "...g....g...",
    "..gggggggg..",
    ".gggggggggg.",
    ".ggkwggkwgg.",
    ".ggkkggkkgg.",
    ".gpggggggpg.",
    "..gggddggg..",
    ".gggggggggg.",
    "..gggggggg..",
    "bccccccccccb",
    "bbbbbbbbbbbb",
]
MASCOT_TITLE = "nook"
MASCOT_TAGLINE = "your cozy reading nook"

# ---- TUI theme (derived from the mascot palette) -----------------------------
THEME_NAME = "nook"
THEME_COLORS = {
    "primary": MASCOT_PALETTE["d"],  # leaf green: focus borders, highlights
    "secondary": MASCOT_PALETTE["g"],  # light green
    "accent": MASCOT_PALETTE["b"],  # book-cover amber: footer keys, links
    "foreground": MASCOT_PALETTE["c"],  # page cream
    "background": "#14181a",
    "surface": "#1b2124",
    "panel": "#222a2e",
    "success": MASCOT_PALETTE["g"],
    "warning": "#e8a857",
    "error": "#ff7b8f",
}
THEME_VARIABLES = {
    "block-cursor-background": MASCOT_PALETTE["d"],
    "block-cursor-foreground": "#0f1512",
    "block-cursor-text-style": "bold",
    "footer-key-foreground": MASCOT_PALETTE["b"],
}
