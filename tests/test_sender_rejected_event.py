"""An event the receiver refuses is set aside; it does not block the ones behind it."""

import hashlib
import json

import httpx
import pytest

from logsentinel.portal.app import create_app
from logsentinel.portal.forward import forward
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store


def receiver(tmp_path):
    app = create_app(tmp_path / "receiver", background=False)
    store = app.state.store
    machine = store.put("machine", Machine(name="remote").model_dump())
    source = store.put("source", Source(name="stream", machine_id=machine, kind="push", enabled=True).model_dump())
    store.set_meta("push:" + source, hashlib.sha256(b"synthetic").hexdigest())
    return app, store, source


def refusing(app, status, marker=b"POISON"):
    """The real receiver, except that a batch carrying the marker is refused."""
    transport = httpx.ASGITransport(app=app)

    class Refusing(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            if request.url.path.startswith("/ingest/") and marker in request.content:
                return httpx.Response(status, json={"detail": "Invalid event"}, request=request)
            return await transport.handle_async_request(request)

    return Refusing()


async def deliver_until_quiet(path, source, spool, rounds=40):
    for _ in range(rounds):
        try:
            await forward(str(path), "http://localhost", source, "synthetic", spool, once=True)
        except RuntimeError:
            pass
        if not Store(spool).events(status="pending"):
            return
    raise AssertionError("the queue never drained")


def use(monkeypatch, transport):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=transport, **{k: v for k, v in kw.items() if k != "transport"}))


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 422])
async def test_a_refused_event_is_set_aside_and_the_rest_are_delivered(tmp_path, monkeypatch, status):
    app, store, source = receiver(tmp_path)
    use(monkeypatch, refusing(app, status))
    path = tmp_path / "app.log"
    path.write_text("".join(f"line {n}\n" for n in range(1, 6)) + "POISON here\n" + "".join(f"line {n}\n" for n in range(6, 11)))
    spool = tmp_path / "spool"
    await deliver_until_quiet(path, source, spool)
    assert sorted(e["message"] for e in store.events(limit=50)) == sorted(f"line {n}" for n in range(1, 11))
    rejected = Store(spool).events(status="rejected")
    assert [e["message"] for e in rejected] == ["POISON here"]
    assert not Store(spool).events(status="pending")


@pytest.mark.asyncio
async def test_a_server_error_is_still_retried_and_nothing_is_set_aside(tmp_path, monkeypatch):
    app, store, source = receiver(tmp_path)
    use(monkeypatch, refusing(app, 500))
    path = tmp_path / "app.log"
    path.write_text("one\nPOISON\nthree\n")
    spool = tmp_path / "spool"
    for _ in range(4):
        with pytest.raises(RuntimeError):
            await forward(str(path), "http://localhost", source, "synthetic", spool, once=True)
    assert len(Store(spool).events(status="pending")) == 3
    assert not Store(spool).events(status="rejected")


@pytest.mark.asyncio
async def test_spool_status_counts_rejected_events(tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from logsentinel import cli

    app, store, source = receiver(tmp_path)
    use(monkeypatch, refusing(app, 400))
    path = tmp_path / "app.log"
    path.write_text("one\nPOISON\n")
    spool = tmp_path / "spool"
    await deliver_until_quiet(path, source, spool)
    result = CliRunner().invoke(cli.app, ["spool-status", "--spool", str(spool)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["counts"]["rejected"] == 1
