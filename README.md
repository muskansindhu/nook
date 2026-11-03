# nook

Local-first, terminal-native reader for developer articles (Hacker News, The Daily Diff, DEV, daily.dev).
This is a proof of concept built from `readr_build_spec.md` (readr → nook).

## Run

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
source .venv/bin/activate
nook init
nook sync            # fetch feeds + cache bodies (works per-source: --source hn)
nook                 # full-screen TUI   (or: nook tui)
```

CLI: `nook feed [hn|tdd|devto|dailydev]`, `read ID`, `bookmark ID`, `bookmarks`, `mark-read/unread ID`,
`history`, `search "query"`, `cache status|download ID|retry-failed|list`, `sources`, `config show`, `doctor`.
IDs are **local nook IDs**. Optional: `export DAILY_DEV_TOKEN=...` to enable daily.dev.

TUI keys: `j/k` move · `Enter` open · `Esc` back · `/` search · `b` bookmark · `m` read/unread ·
`r` sync · `R` retry download · `Tab` switch pane · `?` help · `q` quit.

## Sources
- **hn** – official Firebase API (top/new/best/ask/show); body extracted from the linked page.
- **devto** – Forem API v1 (`Accept: application/vnd.forem.api-v1+json`); body from `body_markdown`.
- **dailydev** – Public API `feeds/foryou` with cursor pagination; needs `DAILY_DEV_TOKEN`.
- **tdd** – tdd.cat advertises a JSON feed (`/json`, `rel=alternate`); editorial "Why read" + summary are cached as the body.

## POC scope / deviations from the spec
- Plain `sqlite3` (+ FTS5, LIKE fallback) instead of SQLAlchemy/Alembic; schema is created idempotently, no migrations yet.
- Dataclasses instead of Pydantic. `venv` + pip instead of `uv`.
- TDD feed only exposes the latest edition; no retry/backoff or `Retry-After` handling yet (errors map to source statuses).
- Cross-source dedupe is by exact canonical URL in the unified feed; per-source rows are kept.
- Tests: `pytest` (adapters mocked with respx, storage, offline-safety, TUI navigation).
