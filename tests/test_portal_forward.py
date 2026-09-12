import hashlib
import asyncio
import json
import time
import httpx
import pytest
from logsentinel.portal.app import create_app
from logsentinel.portal.forward import forward
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store


@pytest.mark.asyncio
async def test_lost_ack_retries_same_events_and_reclaims_sender_spool(
    tmp_path, monkeypatch
):
    app = create_app(tmp_path / "receiver", background=False)
    store = app.state.store
    machine = store.put("machine", Machine(name="remote").model_dump())
    source = store.put(
        "source",
        Source(
            name="stream", machine_id=machine, kind="push", enabled=True
        ).model_dump(),
    )
    store.set_meta("push:" + source, hashlib.sha256(b"synthetic").hexdigest())
    path = tmp_path / "app.log"
    path.write_text("one\ntwo\n")
    original = httpx.AsyncClient
    transport = httpx.ASGITransport(app=app)

    class LostAck(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            await transport.handle_async_request(request)
            raise httpx.ReadTimeout("lost ACK after receiver commit")

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=LostAck(), **kwargs)
    )
    spool = tmp_path / "spool"
    with pytest.raises(RuntimeError):
        await forward(
            str(path), "http://localhost", source, "synthetic", spool, once=True
        )
    assert len(store.events()) == 2
    assert json.loads(store.meta("health:" + source))["status"] == "ok"
    assert len(Store(spool).events(status="pending")) == 2
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
    )
    await forward(str(path), "http://localhost", source, "synthetic", spool, once=True)
    assert len(store.events()) == 2
    assert Store(spool).events() == []
    monkeypatch.chdir(tmp_path)
    await forward(path.name, "http://localhost", source, "synthetic", spool, once=True)
    await forward(str(path), "http://localhost", source, "synthetic", spool, once=True)
    assert len(store.events()) == 2
    with pytest.raises(ValueError, match="another receiver"):
        await forward(
            str(path), "http://localhost", "other", "synthetic", spool, once=True
        )


@pytest.mark.asyncio
async def test_slow_delivery_does_not_stop_capture(tmp_path):
    from logsentinel.portal.sender import run_workers

    store = Store(tmp_path)
    captured = []
    sending = asyncio.Event()

    async def capture():
        captured.append(time.monotonic())

    async def deliver():
        sending.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(run_workers(capture, deliver, 0.05, store, False))
    await sending.wait()
    await asyncio.sleep(0.35)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(captured) >= 3


@pytest.mark.asyncio
async def test_wrong_path_does_not_bind_a_legacy_spool(tmp_path):
    store = Store(tmp_path / "spool")
    original = tmp_path / "original.log"
    original.write_text("entry\n")
    store.put(
        "source",
        Source(
            name="legacy", machine_id="sender", path=str(original), enabled=True
        ).model_dump(),
        "sender",
    )
    with pytest.raises(ValueError, match="another path"):
        await forward(
            str(tmp_path / "wrong.log"),
            "http://localhost",
            "remote",
            "synthetic",
            store.directory,
            once=True,
        )
    assert store.meta("sender_binding") is None
    assert store.get("source", "sender")["path"] == str(original)


def test_spool_rejects_concurrent_senders_and_wrong_identity(tmp_path):
    from logsentinel.portal.sender import spool_lock

    store = Store(tmp_path)
    with spool_lock(store, ["same"]):
        with pytest.raises(ValueError, match="Another sender"):
            with spool_lock(store, ["same"]):
                pass
    with pytest.raises(ValueError, match="another receiver"):
        with spool_lock(store, ["different"]):
            pass


def test_heartbeat_is_source_bound_and_does_not_invent_events(tmp_path):
    from fastapi.testclient import TestClient

    app = create_app(tmp_path, background=False)
    store = app.state.store
    machine = store.put("machine", Machine(name="remote").model_dump())
    source = store.put(
        "source",
        Source(
            name="stream", machine_id=machine, kind="push", enabled=True
        ).model_dump(),
    )
    store.set_meta("push:" + source, hashlib.sha256(b"synthetic").hexdigest())
    with TestClient(app, base_url="http://localhost") as c:
        endpoint = "/heartbeat/" + source
        body = {"ok": True, "pending": 0}
        headers = {"Authorization": "Bearer synthetic"}
        assert c.post(endpoint, json=body).status_code == 401
        assert (
            c.post(endpoint, json=dict(body, pending=-1), headers=headers).status_code
            == 400
        )
        assert c.post(endpoint, json=body, headers=headers).status_code == 200
        assert not store.events()
        c.post(endpoint, json={"ok": False, "pending": 10}, headers=headers)
        c.post(
            "/ingest/" + source,
            json={"events": [{"id": "old", "raw": "history"}]},
            headers=headers,
        )
        assert json.loads(store.meta("health:" + source))["status"] == "error"


@pytest.mark.asyncio
async def test_sender_waits_the_pause_the_receiver_asked_for(tmp_path, monkeypatch):
    """A quota refusal names its own delay; exponential backoff must not shorten it."""
    from logsentinel.portal.sender import run_workers

    store = Store(tmp_path)
    delays = []

    async def record(seconds):
        delays.append(seconds)
        if len(delays) >= 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", record)

    async def capture():
        # Hold the capture loop so only delivery reaches the patched sleep.
        await asyncio.Event().wait()

    results = iter([900, False, False])

    async def deliver():
        return next(results)

    with pytest.raises(asyncio.CancelledError):
        await run_workers(capture, deliver, 60, store, False)
    # 900 is honoured verbatim, and backoff restarts from its base afterwards
    # instead of inheriting the pause.
    assert delays == [900, 4, 8]
