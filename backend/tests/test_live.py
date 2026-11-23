import asyncio
import json

import fakeredis
import pytest

from app import store
from app.config import settings
from app.main import Broadcaster


@pytest.mark.asyncio
async def test_ingest_publishes_only_when_top5_changes():
    settings.news_mock = True
    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    ps = r.pubsub()
    await ps.subscribe(store.NEWS_CHANNEL)
    await ps.get_message(timeout=1)                      # subscribe confirmation
    first = await store.ingest(r, "tech")
    assert len(first) == 5 and await r.exists(f"story:{first[0]['id']}")
    msg = await ps.get_message(timeout=1)
    assert json.loads(msg["data"])["category"] == "tech"
    await store.ingest(r, "tech")                        # same list again: no new publish
    assert await ps.get_message(timeout=0.3) is None


@pytest.mark.asyncio
async def test_one_subscription_fans_out_to_many_listeners():
    r = fakeredis.FakeAsyncRedis(decode_responses=True)
    hub = Broadcaster(r)
    hub.start()
    await asyncio.sleep(0.1)
    with hub.listen(store.NEWS_CHANNEL) as a, hub.listen(store.NEWS_CHANNEL) as b, hub.listen("decode:x") as c:
        await r.publish(store.NEWS_CHANNEL, "hello")
        await r.publish("decode:x", "progress")
        assert await asyncio.wait_for(a.get(), 1) == "hello"
        assert await asyncio.wait_for(b.get(), 1) == "hello"
        assert await asyncio.wait_for(c.get(), 1) == "progress"
    assert not hub.subs                                  # listeners cleaned up when phones disconnect
    await hub.stop()
