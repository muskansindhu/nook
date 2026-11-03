import httpx
import respx

from nook.models import ArticleDraft, FeedOptions
from nook.urls import is_safe_url, normalize_url
from nook.adapters.hackernews import HackerNews
from nook.adapters.devto import DevTo
from nook.adapters.dailydev import DailyDev
from nook.extraction import sanitize


def draft(**kw):
    base = dict(source_id="hn", external_id="1", canonical_url="https://a.com/x", title="T")
    return ArticleDraft(**{**base, **kw})


def test_normalize_url_strips_tracking_keeps_meaningful():
    assert normalize_url("HTTPS://A.com/x/?utm_source=z&id=3") == "https://a.com/x?id=3"


def test_ssrf_guard():
    assert not is_safe_url("file:///etc/passwd")
    assert not is_safe_url("http://127.0.0.1:8080/")
    assert not is_safe_url("javascript:alert(1)")


def test_sanitize_strips_ansi():
    assert sanitize("a\x1b[31mred\x1b[0m\x07b") == "aredb"


def test_upsert_is_idempotent_and_state_survives(nook):
    aid, ins = nook.db.upsert(draft())
    nook.db.set_bookmark(aid, True)
    aid2, ins2 = nook.db.upsert(draft(title="T2"))
    assert (ins, ins2, aid2) == (True, False, aid)
    row = nook.db.get(aid)
    assert row["title"] == "T2" and row["is_bookmarked"] == 1


def test_failed_extraction_keeps_cached_body(nook):
    aid, _ = nook.db.upsert(draft())
    nook.db.save_content(aid, "# hello world body")
    nook.db.mark_content_failed(aid, "failed", "boom")
    row = nook.db.get(aid)
    assert row["content_markdown"] == "# hello world body" and row["content_status"] == "available"


def test_search_hits_body_text_and_unified_dedupe(nook):
    a, _ = nook.db.upsert(draft())
    nook.db.upsert(draft(source_id="tdd", external_id="9"))  # same URL, other source
    nook.db.save_content(a, "the quokka is a marsupial")
    assert [r["id"] for r in nook.db.search("quokka")] == [a]
    assert len(nook.db.list(None)) == 1 and len(nook.db.list("tdd")) == 1


@respx.mock
async def test_hn_adapter_skips_dead_and_non_story():
    base = "https://hacker-news.firebaseio.com/v0"
    respx.get(f"{base}/topstories.json").respond(json=[1, 2, 3])
    respx.get(f"{base}/item/1.json").respond(json={"id": 1, "type": "story", "title": "A", "by": "u", "time": 1700000000, "score": 5, "descendants": 2})
    respx.get(f"{base}/item/2.json").respond(json={"id": 2, "type": "story", "title": "dead", "dead": True})
    respx.get(f"{base}/item/3.json").respond(json={"id": 3, "type": "comment"})
    out = await HackerNews().fetch_feed(FeedOptions(limit=10))
    assert [d.title for d in out] == ["A"]
    assert out[0].canonical_url == "https://news.ycombinator.com/item?id=1"


@respx.mock
async def test_devto_uses_v1_header_and_skips_malformed():
    route = respx.get("https://dev.to/api/articles/latest").respond(
        json=[{"id": 1, "title": "X", "url": "https://dev.to/a/x", "tag_list": ["py"]}, {"bogus": True}]
    )
    out = await DevTo().fetch_feed(FeedOptions(limit=5))
    assert len(out) == 1 and route.calls[0].request.headers["accept"] == "application/vnd.forem.api-v1+json"


@respx.mock
async def test_dailydev_paginates_and_needs_token():
    import pytest
    from nook.models import SourceError

    with pytest.raises(SourceError) as e:
        await DailyDev(None).fetch_feed(FeedOptions())
    assert e.value.status == "needs_auth"
    post = lambda i: {"id": str(i), "title": f"P{i}", "url": f"https://x.com/{i}", "tags": ["a"]}
    respx.get("https://api.daily.dev/public/v1/feeds/foryou").mock(side_effect=[
        httpx.Response(200, json={"data": [post(1)], "pagination": {"hasNextPage": True, "cursor": "c"}}),
        httpx.Response(200, json={"data": [post(2)], "pagination": {"hasNextPage": False}}),
    ])
    assert len(await DailyDev("tok").fetch_feed(FeedOptions(limit=5))) == 2


@respx.mock
async def test_source_failure_does_not_break_others(nook):
    respx.get("https://tdd.cat/json").respond(500)
    respx.get("https://dev.to/api/articles/latest").respond(json=[{"id": 1, "title": "X", "url": "https://dev.to/a/x"}])
    res = await nook.sync(["tdd", "devto"], limit=5, metadata_only=True)
    st = {r.source_id: r.status for r in res}
    assert st == {"tdd": "failed", "devto": "success"}
    assert len(nook.db.list("devto")) == 1
