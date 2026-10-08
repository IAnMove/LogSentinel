"""The spool delivers urgent lines first and drains a backlog at the receiver's pace."""

import asyncio
import hashlib
import json

import httpx
import pytest

from logsentinel.portal import sender as sender_module
from logsentinel.portal.app import create_app
from logsentinel.portal.forward import DELIVERY_BATCH, forward
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store


def central(tmp_path, monkeypatch):
    app = create_app(tmp_path / "receiver", background=False)
    store = app.state.store
    machine = store.put("machine", Machine(name="remote").model_dump())
    source = store.put("source", Source(name="s", machine_id=machine, kind="push", enabled=True).model_dump())
    store.set_meta("push:" + source, hashlib.sha256(b"synthetic").hexdigest())
    requests = []
    transport = httpx.ASGITransport(app=app)

    class Recording(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if request.url.path.startswith("/ingest/"):
                requests.append(json.loads(request.content))
            return await transport.handle_async_request(request)

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=Recording(), **{k: v for k, v in kw.items() if k != "transport"}))
    return store, source, requests


def spool_with(tmp_path, count, urgent_at=None):
    spool = tmp_path / "spool"
    local = Store(spool)
    rows = [dict(origin=f"r{i}", message=f"routine {i}", service="app") for i in range(count)]
    if urgent_at is not None:
        rows.insert(urgent_at, dict(origin="oom", message="Out of memory: Killed process 7 (java)", service="kernel", priority=2))
    local.ingest({"id": "sender", "machine_id": "sender"}, rows)
    return spool


@pytest.mark.asyncio
async def test_an_urgent_line_at_the_tail_of_the_queue_goes_in_the_first_request(tmp_path, monkeypatch):
    store, source, requests = central(tmp_path, monkeypatch)
    spool = spool_with(tmp_path, 2000, urgent_at=2000)
    empty = tmp_path / "quiet.log"
    empty.write_text("")
    await forward(str(empty), "http://localhost", source, "synthetic", spool, once=True)
    first = [e["raw"] for e in requests[0]["events"]]
    assert any(raw.startswith("Out of memory") for raw in first), "the urgent line waited behind the routine backlog"
    assert len(first) == DELIVERY_BATCH


def test_pending_rows_come_urgent_first_then_oldest(tmp_path):
    spool = spool_with(tmp_path, 10, urgent_at=10)
    picked = Store(spool).pending_for_delivery(4)
    assert picked[0]["message"].startswith("Out of memory")
    assert [e["message"] for e in picked[1:]] == ["routine 0", "routine 1", "routine 2"]


@pytest.mark.asyncio
async def test_a_full_batch_asks_the_loop_to_come_straight_back(monkeypatch):
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)
        if len(slept) >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(sender_module.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    answers = iter(["more", "more", True])

    async def deliver():
        return next(answers)

    async def capture():
        await asyncio.Event().wait()  # never returns, so only delivery sleeps

    with pytest.raises(asyncio.CancelledError):
        await sender_module.run_workers(capture, deliver, 2, Store(tmp_path_for(monkeypatch)), False)
    assert slept[:2] == [0.1, 0.1] and slept[2] == 2


def tmp_path_for(monkeypatch):
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp())
