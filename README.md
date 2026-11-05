# nook

Local-first, terminal-native reader for developer articles (Hacker News, The Daily Diff, DEV, daily.dev).
This is a proof of concept built from the original build spec.

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
`r` sync · `n`/`p` next/previous article (reader) · `o` open in browser · `R` retry download · `Tab` switch pane · `?` help · `q` quit.

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

## Roadmap: topic filtering (design, not implemented)
Goal: show only articles about a chosen topic (e.g. travel) without hurting offline-first use.

**Decision engine = a "System 1 / System 2" cascade.** A fast, cheap, intuitive pass decides most
articles; a slower, deliberate pass handles only the uncertain ones.

| Layer | Role | Cost | Offline |
|---|---|---|---|
| 0. Rules | Keyword / domain / tag scoring | free | yes |
| 1. Fast model (System 1) | Small local embedding model compares title + summary to topic prototype sentences, giving a cosine score | ~10 ms/item | yes |
| 2. Slow model (System 2, opt-in) | LLM yes/no judge with a short reason, only for scores between the low and high thresholds | network + money | no |

- Score above the high threshold: accept. Below the low threshold: reject. In between: escalate, or mark "maybe".
- Scoring runs once at sync time and is stored (`topic_scores`: article, topic, score, layer), so reading stays instant and offline.
- Topics are user-defined in the TOML config (`include`/`exclude` terms, prototypes, thresholds).
- `+` / `-` feedback keys add labelled examples that refine the prototypes.

**Research notes**
- "System 1 / System 2" is not an established model-routing term; the standard name is a *model cascade* (cheap model first, escalate on low confidence).
- Zero-shot prompting a small LLM is the least accurate way to classify topics; embeddings with label descriptions, or a few labelled examples, tend to do better and are cheaper.
- Cascades need calibrated thresholds; tune them on a few labelled articles rather than by intuition.
- HN, DEV and daily.dev are tech-heavy, so a travel filter would need extra sources (RSS is the likely route).
