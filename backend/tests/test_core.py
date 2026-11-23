import time

import fakeredis
import httpx
import pytest
import respx

from app import balancer as B
from app.config import ModelSpec, settings
from app.explain import build_messages, validate
from app.news import cluster, parse_feed, rank, story_id

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>RBI cuts repo rate by 25 bps to boost growth - The Hindu</title><link>https://x/1</link>
<pubDate>Mon, 23 Nov 2026 08:00:00 GMT</pubDate><description>&lt;a&gt;RBI&lt;/a&gt; cut rates</description></item>
<item><title>Repo rate cut: RBI lowers rate by 25 bps, EMIs to fall - Mint</title><link>https://x/2</link>
<pubDate>Mon, 23 Nov 2026 09:00:00 GMT</pubDate></item>
<item><title>Cricket team wins series in Australia - NDTV</title><link>https://x/3</link>
<pubDate>Mon, 23 Nov 2026 07:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_parse_cluster_rank():
    items = parse_feed(RSS)
    assert items[0]["source"] == "The Hindu" and "RBI cuts" in items[0]["title"]
    groups = cluster(items)
    assert len(groups) == 2
    top = rank(groups, now=items[0]["published"] + 3600)
    assert top[0]["outlets"] == 2 and "repo" in top[0]["title"].lower()
    assert top[0]["id"] == story_id(top[0]["title"])


def test_validate_tolerates_loose_output():
    out = validate({"headline": "H", "core_idea": "C", "narrative": "p1\n\np2",
                    "who_affected": ["borrowers"], "backstory": ["earlier thing"]})
    assert out["narrative"] == ["p1", "p2"]
    assert out["who_affected"][0]["group"] == "borrowers"
    assert out["backstory"][0]["event"] == "earlier thing"


def test_messages_include_leads():
    story = {"title": "T", "summary": "S", "published": time.time(), "sources": [{"name": "A", "title": "t"}]}
    msgs = build_messages(story, [{"title": "older", "source": "B", "published": time.time() - 86400}])
    assert "older" in msgs[1]["content"] and "PREVIOUS NEWS LEADS" in msgs[1]["content"]


def test_parse_json_strips_thinking():
    assert B.parse_json('<think>hmm</think>\n{"a": 1}') == {"a": 1}
    assert B.parse_json('Here you go: {"a": 2} done') == {"a": 2}


def _bal(lanes):
    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    return B.Balancer(r, lanes, http=httpx.AsyncClient(timeout=5))


def _ok(model):
    return httpx.Response(200, json={"choices": [{"message": {"content": '{"headline":"%s"}' % model}}]})


@pytest.mark.asyncio
@respx.mock
async def test_failover_on_429_and_cooldown():
    settings.llm_mock = False
    big = B.Lane("k", ModelSpec("big", 30, 5))
    small = B.Lane("k", ModelSpec("small", 30, 1))
    bal = _bal([big, small])

    def handler(request):
        model = __import__("json").loads(request.content)["model"]
        if model == "big":
            return httpx.Response(429, headers={"retry-after": "30"})
        return _ok(model)

    respx.post(f"{settings.groq_base}/chat/completions").mock(side_effect=handler)
    data, model = await bal.chat_json([{"role": "user", "content": "x"}])
    assert model == "small" and data["headline"] == "small"
    assert await bal.r.exists(big.k("cool"))           # big is cooling, so the next call goes straight to small
    _, model2 = await bal.chat_json([{"role": "user", "content": "x"}])
    assert model2 == "small"


@pytest.mark.asyncio
@respx.mock
async def test_respects_rpm_and_spreads_load():
    settings.llm_mock = False
    lanes = [B.Lane("k", ModelSpec(f"m{i}", 3, 1)) for i in range(3)]
    bal = _bal(lanes)
    respx.post(f"{settings.groq_base}/chat/completions").mock(
        side_effect=lambda req: _ok(__import__("json").loads(req.content)["model"]))
    used = [ (await bal.chat_json([{"role": "user", "content": "x"}]))[1] for _ in range(9)]
    assert sorted(set(used)) == ["m0", "m1", "m2"]
    assert all(used.count(m) == 3 for m in ("m0", "m1", "m2"))  # never above each model's 3 RPM
    with pytest.raises(B.LLMError):
        await bal.chat_json([{"role": "user", "content": "x"}], wait_budget=0.5)
