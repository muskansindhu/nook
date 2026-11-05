from nook.models import ArticleDraft
from nook.tui import NookApp, ReaderScreen


async def test_navigate_open_bookmark_back(nook):
    for i in range(3):
        a, _ = nook.db.upsert(ArticleDraft(source_id="hn", canonical_url=f"https://a.com/{i}", title=f"Title {i}", external_id=str(i)))
        nook.db.save_content(a, f"# Body {i}\n\ntext " * 30)
    app = NookApp(nook)
    async with app.run_test() as pilot:
        await pilot.press("j")
        await pilot.press("enter")
        await pilot.pause()
        assert isinstance(app.screen, ReaderScreen)
        await pilot.press("b")
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ReaderScreen)
        assert len(nook.db.list(None, bookmarked=True)) == 1
        assert nook.db.list(None, history=True)  # opening recorded history


async def test_mascot_stays_visible(nook):
    from textual.widgets import Static

    app = NookApp(nook)
    async with app.run_test() as pilot:
        await pilot.pause(2.5)  # long after any would-be splash timeout
        brand = app.query_one("#brand", Static)
        assert brand.region.height > 0 and "nook" in str(brand.render())


async def test_reader_next_prev_and_browser(nook, monkeypatch):
    import webbrowser

    opened = []
    monkeypatch.setattr(webbrowser, "open", lambda u: opened.append(u) or True)
    for i in range(3):
        a, _ = nook.db.upsert(ArticleDraft(source_id="hn", canonical_url=f"https://a.com/{i}", title=f"Title {i}", external_id=str(i)))
        nook.db.save_content(a, f"# Body {i}\n\ntext " * 30)
    app = NookApp(nook)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        await pilot.pause()
        first = app.screen.aid
        await pilot.press("n")
        await pilot.pause()
        second = app.screen.aid
        assert second != first
        await pilot.press("p")
        await pilot.pause()
        assert app.screen.aid == first
        await pilot.press("p")  # already at the top: stays put
        await pilot.pause()
        assert app.screen.aid == first
        await pilot.press("o")
        assert opened and opened[0].startswith("https://a.com/")
        await pilot.press("escape")
        await pilot.pause()
        assert nook.db.get(second)["is_read"]  # stepping counts as opening
