from __future__ import annotations

import asyncio
import sys
from typing import Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.markup import escape

from nook import __version__
from nook.config import ConfigError, config_path, load_config
from nook.constants import DEFAULT_TOML, DOCTOR_TIMEOUT_S, DOCTOR_URLS, SOURCE_IDS, SYNC_UNBOUNDED_LIMIT
from nook.fmt import article_table, fallback_markdown
from nook.service import Nook

app = typer.Typer(
    help="nook — a local-first terminal reader for HN, The Daily Diff, DEV and daily.dev.\n\n"
         "Article IDs are LOCAL nook IDs (shown in the ID column), not the source platform's IDs.",
    no_args_is_help=False, add_completion=False,
)
cache_app = typer.Typer(help="Inspect and fill the offline content cache.")
config_app = typer.Typer(help="Show configuration.")
sources_app = typer.Typer(help="List, enable or disable sources.", invoke_without_command=True)
app.add_typer(cache_app, name="cache")
app.add_typer(config_app, name="config")
app.add_typer(sources_app, name="sources")
out, err = Console(), Console(stderr=True)


def _nook() -> Nook:
    try:
        return Nook(load_config())
    except ConfigError as e:
        err.print(f"[red]Config error:[/red] {escape(str(e))}")
        raise typer.Exit(2)


def _need(n: Nook, aid: int):
    a = n.db.get(aid)
    if a is None:
        err.print(f"[red]No article with local ID {aid}.[/red] Run `nook feed` to see IDs.")
        raise typer.Exit(1)
    return a


def version_cb(v: bool):
    if v:
        out.print(f"nook {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, version: bool = typer.Option(False, "--version", callback=version_cb, is_eager=True)):
    if ctx.invoked_subcommand is None:
        if sys.stdout.isatty() and sys.stdin.isatty():
            tui()
        else:
            out.print(ctx.get_help())


@app.command()
def tui():
    """Launch the full-screen reader."""
    from nook.tui import NookApp

    NookApp(_nook()).run()


@app.command()
def init():
    """Create the config file and database."""
    p = config_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(DEFAULT_TOML)
        out.print(f"Wrote config: {p}")
    n = _nook()
    out.print(f"Database ready: {n.cfg.db_path}")
    out.print("Optional: export DAILY_DEV_TOKEN=... to enable daily.dev. Then run [bold]nook sync[/bold].")


@config_app.command("path")
def config_path_cmd():
    out.print(str(config_path()))


@config_app.command("show")
def config_show():
    c = load_config()
    out.print(f"config file : {config_path()} ({'exists' if config_path().exists() else 'missing, using defaults'})")
    out.print(f"database    : {c.db_path}")
    out.print(f"limit       : {c.default_limit}  auto-download/sync: {c.max_auto_download}")
    states = ", ".join(f"{k}={'on' if v else 'off'}" for k, v in c.enabled.items())
    out.print(f"sources     : {states}")
    out.print(f"daily.dev   : token {'set' if c.daily_dev_token else 'NOT set'}")


@sources_app.callback()
def sources_list(ctx: typer.Context):
    if ctx.invoked_subcommand:
        return
    n = _nook()
    for s in n.db.sources():
        on = n.cfg.enabled.get(s["id"], True)
        out.print(f"[bold]{s['id']:9}[/bold] {s['name']:16} {'enabled ' if on else 'disabled'} "
                  f"status={s['status']:24} last sync: {s['last_synced_at'] or 'never'}"
                  + (f"\n          [yellow]{escape(s['last_error'])}[/yellow]" if s["last_error"] else ""))


def _toggle(sid: str, value: bool):
    if sid not in SOURCE_IDS:
        err.print(f"Unknown source '{sid}'. Choose from: {', '.join(SOURCE_IDS)}")
        raise typer.Exit(1)
    p = config_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(DEFAULT_TOML)
    lines, i = p.read_text().splitlines(), 0
    for i, line in enumerate(lines):
        if line.strip() == f"[sources.{sid}]":
            lines[i + 1] = f"enabled = {'true' if value else 'false'}"
            break
    else:
        lines += [f"[sources.{sid}]", f"enabled = {'true' if value else 'false'}"]
    p.write_text("\n".join(lines) + "\n")
    out.print(f"{sid} {'enabled' if value else 'disabled'}")


@sources_app.command("enable")
def sources_enable(source: str):
    _toggle(source, True)


@sources_app.command("disable")
def sources_disable(source: str):
    _toggle(source, False)


@app.command()
def doctor():
    """Check config, database and connectivity (never prints secrets)."""
    import httpx

    ok = True
    try:
        n = Nook(load_config())
        out.print(f"[green]✓[/green] config parses ({config_path()})")
        out.print(f"[green]✓[/green] database readable: {n.cfg.db_path} (FTS5: {'yes' if n.db.has_fts else 'no, using LIKE'})")
    except Exception as e:
        err.print(f"[red]✗[/red] {escape(str(e))}")
        raise typer.Exit(1)
    if n.cfg.enabled.get("dailydev") and not n.cfg.daily_dev_token:
        out.print("[yellow]![/yellow] daily.dev enabled but DAILY_DEV_TOKEN is not set")
    for sid in n.adapters:
        try:
            r = httpx.get(DOCTOR_URLS[sid], timeout=DOCTOR_TIMEOUT_S, headers={"Accept": "application/vnd.forem.api-v1+json"})
            out.print(f"[green]✓[/green] {sid}: reachable (HTTP {r.status_code})")
        except httpx.HTTPError as e:
            ok = False
            out.print(f"[yellow]![/yellow] {sid}: unreachable ({type(e).__name__}) — offline reading still works")
    raise typer.Exit(0 if ok else 0)


@app.command()
def sync(
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Only this source"),
    metadata_only: bool = typer.Option(False, "--metadata-only"),
    download_content: bool = typer.Option(False, "--download-content", help="Download ALL missing bodies"),
    force: bool = typer.Option(False, "--force", help="Re-fetch bodies even if cached"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n"),
):
    """Fetch feeds from sources and cache article bodies."""
    n = _nook()
    if source and source not in n.adapters:
        err.print(f"Source '{source}' is unknown or disabled.")
        raise typer.Exit(1)
    with out.status("Syncing…"):
        results = asyncio.run(n.sync([source] if source else None, limit, metadata_only, download_content, force))
    failed = 0
    for r in results:
        if r.status == "failed":
            failed += 1
            out.print(f"[red]✗[/red] {r.source_id:9} {escape(r.error or '')}")
        else:
            out.print(f"[green]✓[/green] {r.source_id:9} {r.fetched} fetched, {r.inserted} new, {r.updated} updated, "
                      f"{r.downloaded} bodies cached")
    if failed == len(results):
        err.print("[yellow]All sources failed — are you offline? Cached articles are still readable.[/yellow]")
        raise typer.Exit(1)


@app.command()
def feed(
    source: Optional[str] = typer.Argument(None, help="hn | tdd | devto | dailydev (omit for unified feed)"),
    limit: Optional[int] = typer.Option(None, "--limit", "-n"),
    unread: bool = typer.Option(False, "--unread"),
    sort: str = typer.Option("newest", "--sort", help="newest | popular | discussed"),
):
    """Show cached articles (works offline). Run `nook sync` to refresh."""
    n = _nook()
    if source and source not in SOURCE_IDS:
        err.print(f"Unknown source '{source}'.")
        raise typer.Exit(1)
    rows = n.db.list(source, limit or n.cfg.default_limit, unread=unread, sort=sort)
    if not rows:
        out.print("No cached articles. Run [bold]nook sync[/bold] first.")
        return
    out.print(article_table(rows))
    out.print("[dim]★ bookmarked  ✓ read  • unread  ▣ cached offline  ▢ not downloaded · IDs are local nook IDs[/dim]")


@app.command()
def read(
    article_id: int,
    plain: bool = typer.Option(False, "--plain"),
    no_mark_read: bool = typer.Option(False, "--no-mark-read"),
    open_url: bool = typer.Option(False, "--open-url", help="Open the original URL in your browser (opt-in)"),
):
    """Read an article in the terminal (downloads it if not cached)."""
    n = _nook()
    a = _need(n, article_id)
    if open_url:
        import webbrowser

        webbrowser.open(a["canonical_url"])
        return
    if not a["content_markdown"]:
        with out.status("Downloading article…"):
            asyncio.run(n.ensure_content(article_id))
        a = n.db.get(article_id)
    out.print(f"[bold]{escape(a['title'])}[/bold]")
    from nook.fmt import meta_line

    out.print(f"[dim]{escape(meta_line(a))}[/dim]\n[dim]{escape(a['canonical_url'])}[/dim]\n")
    if a["content_markdown"]:
        out.print(a["content_text"] if plain else Markdown(a["content_markdown"]))
    else:
        out.print(Markdown(fallback_markdown(a)))
    if not no_mark_read and n.cfg.auto_mark_read:
        n.db.touch_opened(article_id)
        n.db.set_read(article_id, True)


@app.command()
def bookmark(article_id: int):
    n = _nook(); _need(n, article_id); n.db.set_bookmark(article_id, True); out.print(f"★ bookmarked {article_id}")


@app.command()
def unbookmark(article_id: int):
    n = _nook(); _need(n, article_id); n.db.set_bookmark(article_id, False); out.print(f"unbookmarked {article_id}")


@app.command()
def bookmarks(limit: int = typer.Option(50, "--limit", "-n")):
    n = _nook()
    rows = n.db.list(None, limit, bookmarked=True, dedupe=False)
    out.print(article_table(rows, "Bookmarks") if rows else "No bookmarks yet.")


@app.command("mark-read")
def mark_read(article_id: int):
    n = _nook(); _need(n, article_id); n.db.set_read(article_id, True); out.print(f"marked {article_id} read")


@app.command("mark-unread")
def mark_unread(article_id: int):
    n = _nook(); _need(n, article_id); n.db.set_read(article_id, False); out.print(f"marked {article_id} unread")


@app.command()
def history(limit: int = typer.Option(20, "--limit", "-n")):
    n = _nook()
    rows = n.db.list(None, limit, history=True, dedupe=False)
    out.print(article_table(rows, "Recently read") if rows else "Nothing read yet.")


@app.command()
def search(
    query: str,
    source: Optional[str] = typer.Option(None, "--source"),
    unread: bool = typer.Option(False, "--unread"),
    bookmarked: bool = typer.Option(False, "--bookmarked"),
    limit: int = typer.Option(30, "--limit", "-n"),
):
    """Full-text search over cached titles, descriptions, tags and bodies (offline)."""
    n = _nook()
    rows = n.db.search(query, source, unread, bookmarked, limit)
    out.print(article_table(rows, f"Results for “{query}”") if rows else "No matches.")


@cache_app.command("status")
def cache_status():
    s = _nook().db.cache_stats()
    out.print(f"{s.get('available', 0)} of {s['total']} articles cached for offline reading")
    for k in ("pending", "failed", "unavailable", "blocked"):
        if s.get(k):
            out.print(f"  {k}: {s[k]}")


@cache_app.command("download")
def cache_download(article_id: int, force: bool = typer.Option(False, "--force")):
    n = _nook(); _need(n, article_id)
    status, error = asyncio.run(n.ensure_content(article_id, force))
    if status == "available":
        out.print(f"[green]✓[/green] cached {article_id}")
    else:
        err.print(f"[red]✗[/red] {status}: {escape(error or '')}")
        raise typer.Exit(1)


@cache_app.command("retry-failed")
def cache_retry():
    n = _nook()
    ids = [r["id"] for r in n.db.list(None, SYNC_UNBOUNDED_LIMIT, missing_content=True, dedupe=False)
           if r["content_status"] in ("failed", "pending")]
    res = asyncio.run(n.download_many(ids))
    out.print(f"{sum(ok for _, ok in res)} of {len(ids)} downloaded")


@cache_app.command("list")
def cache_list(missing_content: bool = typer.Option(False, "--missing-content"), limit: int = 50):
    n = _nook()
    rows = n.db.list(None, limit, missing_content=missing_content, dedupe=False)
    out.print(article_table(rows) if rows else "Nothing to show.")
