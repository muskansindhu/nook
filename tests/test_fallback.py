import respx

from nook.adapters.hackernews import HackerNews
from nook.fmt import fallback_markdown
from nook.models import ArticleDraft

JS_SHELL = (
    "<html><head><title>Concepts</title>"
    '<meta name="description" content="Interactive explainers for CS concepts.">'
    "</head><body><main><p>This page needs JavaScript.</p></main></body></html>"
)


@respx.mock
async def test_js_only_page_keeps_summary_and_links_discussion(nook):
    respx.get("https://js.example.com/").respond(text=JS_SHELL, headers={"content-type": "text/html"})
    aid, _ = nook.db.upsert(ArticleDraft(
        source_id="hn", canonical_url="https://js.example.com", title="Show HN: x", external_id="1",
        metadata={"hn_url": "https://news.ycombinator.com/item?id=1"},
    ))
    status, _ = await nook.ensure_content(aid)
    row = nook.db.get(aid)
    assert status == "unavailable" and row["content_markdown"] is None
    md = fallback_markdown(row)
    assert "Interactive explainers" in md and "JavaScript" in md
    assert "https://news.ycombinator.com/item?id=1" in md
    assert "Press R" not in md  # retrying can't help a JS-only page


@respx.mock
async def test_ask_hn_text_becomes_article_body():
    base = "https://hacker-news.firebaseio.com/v0"
    respx.get(f"{base}/askstories.json").respond(json=[7])
    respx.get(f"{base}/item/7.json").respond(json={
        "id": 7, "type": "story", "title": "Ask HN: q?", "time": 1700000000,
        "text": "First para.<p>See <a href=\"https://x.com\">this</a>.<p><pre><code>code()</code></pre>",
    })
    from nook.models import FeedOptions

    [d] = await HackerNews().fetch_feed(FeedOptions(limit=5, kind="ask"))
    assert "First para." in d.content_markdown and "[this](https://x.com)" in d.content_markdown
    assert "```" in d.content_markdown
