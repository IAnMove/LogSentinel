"""A sender forwards access-log lines like any other; only the central decides what the model reads."""

import hashlib

import httpx
import pytest

from logsentinel.portal.app import create_app
from logsentinel.portal.forward import forward
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store

ACCESS = '192.0.2.1 - - [07/Oct/2026:10:00:00 +0000] "GET /index.html HTTP/1.1" 200 12 "-" "curl/8"'


def central(tmp_path, monkeypatch):
    app = create_app(tmp_path / "receiver", background=False)
    store = app.state.store
    machine = store.put("machine", Machine(name="remote").model_dump())
    source = store.put("source", Source(name="web", machine_id=machine, kind="push", enabled=True).model_dump())
    store.set_meta("push:" + source, hashlib.sha256(b"synthetic").hexdigest())
    original = httpx.AsyncClient
    transport = httpx.ASGITransport(app=app)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}))
    return store, source


@pytest.mark.asyncio
async def test_access_log_lines_are_delivered_and_leave_the_spool(tmp_path, monkeypatch):
    store, source = central(tmp_path, monkeypatch)
    path = tmp_path / "access.log"
    path.write_text(ACCESS + "\nplain error line\n")
    spool = tmp_path / "spool"
    for _ in range(2):
        await forward(str(path), "http://localhost", source, "synthetic", spool, once=True)
    delivered = {e["message"]: e for e in store.events(limit=10)}
    assert ACCESS in delivered and delivered[ACCESS]["status"] == "sampled", "the central keeps it from the model"
    assert "plain error line" in delivered
    local = Store(spool)
    assert not local.events(status="pending") and not local.events(status="sampled")
    assert local.sender_pending() == 0


@pytest.mark.asyncio
async def test_a_spool_left_with_sampled_lines_by_the_earlier_build_is_healed(tmp_path, monkeypatch):
    store, source = central(tmp_path, monkeypatch)
    spool = tmp_path / "spool"
    local = Store(spool)
    local.ingest({"id": "sender", "machine_id": "sender"}, [dict(origin="w1", message=ACCESS, service="web-access", metadata={"web": {"ip": "192.0.2.1"}})])
    with local.connect() as db:
        db.execute("UPDATE events SET status='sampled'")
    path = tmp_path / "access.log"
    path.write_text("")
    await forward(str(path), "http://localhost", source, "synthetic", spool, once=True)
    assert [e["message"] for e in store.events(limit=10)] == [ACCESS]
    assert Store(spool).sender_pending() == 0
