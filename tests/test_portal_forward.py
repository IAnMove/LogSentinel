import hashlib
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
    assert len(Store(spool).events(status="pending")) == 2
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kwargs: original(transport=transport, **kwargs)
    )
    await forward(str(path), "http://localhost", source, "synthetic", spool, once=True)
    assert len(store.events()) == 2
    assert Store(spool).events() == []
    await forward(str(path), "http://localhost", source, "synthetic", spool, once=True)
    assert len(store.events()) == 2
