from __future__ import annotations

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Footer, Header, Input, Markdown, OptionList, Static
from textual.widgets.option_list import Option

from nook.constants import MASCOT_TAGLINE, MASCOT_TITLE, TUI_PAGE_SIZE, TUI_VIEWS
from nook.fmt import flags, meta_line, render_mascot
from nook.service import Nook



def article_option(a) -> Option:
    t = Text()
    t.append(f"{flags(a)} ", style="yellow" if a["is_bookmarked"] else "dim")
    t.append(a["title"], style="dim" if a["is_read"] else "bold")
    t.append("\n    " + meta_line(a), style="dim")
    return Option(t, id=str(a["id"]))


class ListNav:
    """j/k/g/G on top of an OptionList."""

    def _ol(self) -> OptionList:
        return self.query_one("#articles", OptionList)

    def action_down(self): self._ol().action_cursor_down()
    def action_up(self): self._ol().action_cursor_up()
    def action_top(self): self._ol().action_first()
    def action_bottom(self): self._ol().action_last()


class ReaderScreen(Screen):
    BINDINGS = [
        Binding("escape,q", "back", "Back"), Binding("b", "bookmark", "Bookmark"),
        Binding("m", "toggle_read", "Mark read/unread"), Binding("j,down", "scroll(1)", "Down", show=False),
        Binding("k,up", "scroll(-1)", "Up", show=False), Binding("space,pagedown", "page(1)", "Page ↓", show=False),
        Binding("pageup", "page(-1)", "Page ↑", show=False), Binding("g", "top", "Top", show=False),
        Binding("G", "bottom", "Bottom", show=False), Binding("R", "retry", "Retry download"),
    ]

    def __init__(self, nook: Nook, aid: int):
        super().__init__()
        self.nook, self.aid = nook, aid

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(id="meta")
        with VerticalScroll(id="body"):
            yield Markdown(id="md")
        yield Footer()

    def on_mount(self) -> None:
        self.render_article()
        a = self.nook.db.get(self.aid)
        if not a["content_markdown"]:
            self.download()
        else:
            self.call_after_refresh(self._restore)

    def _restore(self) -> None:
        body = self.query_one("#body", VerticalScroll)
        p = self.nook.db.get(self.aid)["read_progress"]
        if 0 < p < 0.98 and body.max_scroll_y:
            body.scroll_to(y=p * body.max_scroll_y, animate=False)

    def render_article(self) -> None:
        a = self.nook.db.get(self.aid)
        self.sub_title = a["title"]
        cached = "cached offline" if a["content_markdown"] else "not downloaded"
        star = "★ " if a["is_bookmarked"] else ""
        self.query_one("#meta", Static).update(
            Text.assemble((f"{star}{a['title']}\n", "bold"), (f"{meta_line(a)} · {cached}\n{a['canonical_url']}", "dim"))
        )
        if a["content_markdown"]:
            md = a["content_markdown"]
        else:
            md = (a["description"] or "") + f"\n\n*Full text {a['content_status']}" + (
                f": {a['content_error']}" if a["content_error"] else "") + ". Press **R** to retry.*"
        self.query_one("#md", Markdown).update(md)

    @work(exclusive=True)
    async def download(self, force: bool = False) -> None:
        self.notify("Downloading article…")
        status, error = await self.nook.ensure_content(self.aid, force)
        self.render_article()
        if status != "available":
            self.notify(f"Could not download: {error}", severity="warning")
        else:
            self.call_after_refresh(self._restore)

    def action_retry(self) -> None: self.download(force=True)
    def action_scroll(self, n: int) -> None: self.query_one("#body").scroll_relative(y=n * 2, animate=False)
    def action_page(self, n: int) -> None: self.query_one("#body").scroll_page_down() if n > 0 else self.query_one("#body").scroll_page_up()
    def action_top(self) -> None: self.query_one("#body").scroll_home(animate=False)
    def action_bottom(self) -> None: self.query_one("#body").scroll_end(animate=False)

    def action_bookmark(self) -> None:
        a = self.nook.db.get(self.aid)
        self.nook.db.set_bookmark(self.aid, not a["is_bookmarked"])
        self.render_article()

    def action_toggle_read(self) -> None:
        a = self.nook.db.get(self.aid)
        self.nook.db.set_read(self.aid, not a["is_read"])
        self.notify("Marked unread" if a["is_read"] else "Marked read")

    def action_back(self) -> None:
        body = self.query_one("#body", VerticalScroll)
        if body.max_scroll_y:
            self.nook.db.set_progress(self.aid, body.scroll_y / body.max_scroll_y)
        self.app.pop_screen()


class SearchScreen(ModalScreen[int | None]):
    BINDINGS = [Binding("escape", "dismiss(None)", "Close"), Binding("down", "focus_list", "Results", show=False)]

    def __init__(self, nook: Nook):
        super().__init__()
        self.nook = nook

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Search cached titles, tags and article text…  (Enter to search, ↓ for results)", id="q")
        yield OptionList(id="results")

    def on_mount(self) -> None:
        self.query_one("#q").focus()

    def on_input_submitted(self, e: Input.Submitted) -> None:
        ol = self.query_one("#results", OptionList)
        ol.clear_options()
        rows = self.nook.db.search(e.value.strip(), limit=50) if e.value.strip() else []
        ol.add_options([article_option(a) for a in rows] or [Option("No matches", disabled=True)])
        if rows:
            ol.focus()

    def action_focus_list(self) -> None: self.query_one("#results").focus()

    def on_option_list_option_selected(self, e: OptionList.OptionSelected) -> None:
        if e.option.id:
            self.dismiss(int(e.option.id))


class HelpScreen(ModalScreen):
    BINDINGS = [Binding("escape,q,question_mark", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        yield Static(
            "[b]nook keys[/b]\n\n"
            "j/k ↑/↓   move          g/G   top/bottom\n"
            "Enter     open          Esc   back\n"
            "Tab       switch pane   /     search (offline)\n"
            "b         bookmark      m     mark read/unread\n"
            "r         refresh feed  R     retry download (reader)\n"
            "q         quit / back   ?     this help\n\n"
            "Flags: ★ bookmarked  ✓ read  • unread  ▣ cached  ▢ not downloaded",
            id="help",
        )


class NookApp(App, ListNav):
    TITLE = "nook"
    CSS = """
    #sidebar { width: 24; border-right: solid $primary-darken-2; }
    #brand { height: auto; width: 100%; content-align: center middle; text-align: center; padding: 1 0 0 0; }
    #views { height: 1fr; }
    #articles { width: 1fr; }
    #meta { padding: 0 2; background: $boost; height: auto; }
    #body { padding: 0 2; }
    #help { padding: 2 4; width: 64; height: auto; border: round $primary; background: $surface; }
    HelpScreen { align: center middle; }
    SearchScreen { align: center top; }
    SearchScreen > Input { margin: 2 4 0 4; }
    SearchScreen > OptionList { margin: 0 4; height: 70%; }
    """
    BINDINGS = [
        Binding("q", "quit_or_back", "Quit"), Binding("j", "down", "Down", show=False),
        Binding("k", "up", "Up", show=False), Binding("g", "top", "Top", show=False),
        Binding("G", "bottom", "Bottom", show=False), Binding("b", "bookmark", "Bookmark"),
        Binding("m", "toggle_read", "Read/unread"), Binding("r", "refresh", "Refresh"),
        Binding("slash", "search", "Search"), Binding("question_mark", "help", "Help"),
        Binding("tab", "swap_pane", "Switch pane", show=False),
    ]

    def __init__(self, nook: Nook):
        super().__init__()
        self.nook = nook
        self.view = "all"

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal():
            with Vertical(id="sidebar"):
                yield Static(Text.assemble(render_mascot(), (MASCOT_TITLE, "bold #8be28b"), "\n", (MASCOT_TAGLINE, "dim")), id="brand")
                yield OptionList(*[Option(label, id=vid) for vid, label in TUI_VIEWS], id="views")
            yield OptionList(id="articles")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#views", OptionList).highlighted = 0
        self.load_articles()
        self.query_one("#articles").focus()
        if not self.nook.db.list(limit=1):
            self.notify("No articles yet — press r to sync.", timeout=6)
        self._status()

    def _status(self, online: bool | None = None) -> None:
        syncs = [s["last_synced_at"] for s in self.nook.db.sources() if s["last_synced_at"]]
        last = max(syncs)[:16].replace("T", " ") if syncs else "never"
        net = "" if online is None else ("online · " if online else "OFFLINE · ")
        self.sub_title = f"{net}last sync {last}"

    def load_articles(self, keep: bool = False) -> None:
        ol = self.query_one("#articles", OptionList)
        idx = ol.highlighted or 0
        v, db = self.view, self.nook.db
        if v in ("bookmarks", "unread", "history"):
            rows = db.list(None, TUI_PAGE_SIZE, bookmarked=v == "bookmarks", unread=v == "unread", history=v == "history", dedupe=False)
        else:
            rows = db.list(None if v == "all" else v, TUI_PAGE_SIZE)
        ol.clear_options()
        ol.add_options([article_option(a) for a in rows] or [Option("Nothing here yet.", disabled=True)])
        if rows:
            ol.highlighted = min(idx, len(rows) - 1) if keep else 0

    def on_option_list_option_highlighted(self, e: OptionList.OptionHighlighted) -> None:
        if e.option_list.id == "views" and e.option.id and e.option.id != self.view:
            self.view = e.option.id
            self.load_articles()

    def on_option_list_option_selected(self, e: OptionList.OptionSelected) -> None:
        if e.option_list.id == "articles" and e.option.id:
            self.open_article(int(e.option.id))
        elif e.option_list.id == "views":
            self.query_one("#articles").focus()

    def open_article(self, aid: int) -> None:
        self.nook.db.touch_opened(aid)
        if self.nook.cfg.auto_mark_read:
            self.nook.db.set_read(aid, True)
        self.push_screen(ReaderScreen(self.nook, aid), lambda _: self.load_articles(keep=True))

    def _current_id(self) -> int | None:
        ol = self.query_one("#articles", OptionList)
        if ol.highlighted is None:
            return None
        o = ol.get_option_at_index(ol.highlighted)
        return int(o.id) if o.id else None

    def action_bookmark(self) -> None:
        if (aid := self._current_id()) and isinstance(self.screen, type(self.screen)) and self.screen is self.screen_stack[0]:
            a = self.nook.db.get(aid)
            self.nook.db.set_bookmark(aid, not a["is_bookmarked"])
            self.load_articles(keep=True)

    def action_toggle_read(self) -> None:
        if (aid := self._current_id()) and self.screen is self.screen_stack[0]:
            self.nook.db.set_read(aid, not self.nook.db.get(aid)["is_read"])
            self.load_articles(keep=True)

    def action_search(self) -> None:
        if self.screen is not self.screen_stack[0]:
            return
        self.push_screen(SearchScreen(self.nook), lambda aid: self.open_article(aid) if aid else None)

    def action_help(self) -> None: self.push_screen(HelpScreen())
    def action_swap_pane(self) -> None:
        self.query_one("#articles" if self.focused and self.focused.id == "views" else "#views").focus()

    def action_quit_or_back(self) -> None:
        if len(self.screen_stack) > 1:
            self.pop_screen()
        else:
            self.exit()

    def action_refresh(self) -> None:
        self.notify("Syncing in the background…")
        self.sync_now()

    @work(exclusive=True)
    async def sync_now(self) -> None:
        sids = None if self.view not in self.nook.adapters else [self.view]
        results = await self.nook.sync(sids, limit=self.nook.cfg.default_limit)
        online = any(r.status != "failed" or "network" not in (r.error or "") for r in results)
        bad = [r for r in results if r.status == "failed"]
        self.load_articles(keep=True)
        self._status(online)
        if len(bad) == len(results):
            self.notify("Sync failed — offline? Cached articles still available.", severity="warning")
        else:
            msg = f"Synced. {sum(r.inserted for r in results)} new."
            if bad:
                msg += " Failed: " + ", ".join(r.source_id for r in bad)
            self.notify(msg)
