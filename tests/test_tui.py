from nook.models import ArticleDraft
from nook.tui import NookApp, ReaderScreen


async def test_navigate_open_bookmark_back(nook):
    for i in range(3):
        a, _ = nook.db.upsert(ArticleDraft("hn", f"https://a.com/{i}", f"Title {i}", external_id=str(i)))
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
