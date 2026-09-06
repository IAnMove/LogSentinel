import hashlib, hmac, json
import httpx
import pytest
from logsentinel.portal.store import Store
from logsentinel.portal.models import Destination
from logsentinel.portal.notify import Outbox


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind", ["telegram", "slack", "discord", "hermes", "n8n", "webhook"]
)
async def test_outgoing_contracts(tmp_path, monkeypatch, kind):
    captured = []

    def handler(req):
        captured.append(req)
        return httpx.Response(200, json={"ok": True, "status": "delivered"})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    dest = Destination(
        name="test",
        kind=kind,
        url="https://synthetic.invalid/hook",
        token="testtoken",
        secret="signing-secret",
        chat_id="42",
    ).model_dump()
    status = await Outbox(Store(tmp_path)).send(
        dest,
        {
            "delivery_id": "fixed-id",
            "title": "<script>",
            "summary": "token=secret123",
            "severity": "HIGH",
        },
    )
    req = captured[0]
    assert "secret123" not in req.content.decode()
    if kind == "hermes":
        stamp = req.headers["X-Webhook-Timestamp"]
        signature = hmac.new(
            b"signing-secret", stamp.encode() + b"." + req.content, hashlib.sha256
        ).hexdigest()
        assert req.headers["X-Webhook-Signature-V2"] == signature
        assert req.headers["X-Request-ID"] == "fixed-id"
    if kind == "discord":
        assert json.loads(req.content)["allowed_mentions"] == {"parse": []}
    assert status in ("delivered", "accepted")


@pytest.mark.asyncio
async def test_file_destination_contained(tmp_path):
    s = Store(tmp_path)
    d = Destination(name="bad", kind="file", path="../../outside").model_dump()
    with pytest.raises(ValueError):
        await Outbox(s).send(d, {"delivery_id": "x"})


@pytest.mark.asyncio
async def test_cancelled_send_is_unknown_and_worker_stops(tmp_path):
    import asyncio, time
    from logsentinel.portal.store import dumps

    s = Store(tmp_path)
    d = s.put(
        "destination", Destination(name="local", kind="file", enabled=True).model_dump()
    )
    with s.connect() as db:
        db.execute(
            "INSERT INTO deliveries VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                "q",
                d,
                "p",
                dumps({"delivery_id": "q"}),
                "pending",
                0,
                time.time(),
                time.time(),
                0,
                None,
            ),
        )
    outbox = Outbox(s)

    async def interrupted(*args):
        raise asyncio.CancelledError()

    outbox.send = interrupted
    with pytest.raises(asyncio.CancelledError):
        await outbox.drain()
    assert s.rows("deliveries")[0]["status"] == "unknown"


@pytest.mark.asyncio
async def test_file_destination_rotation_compresses_and_bounds_archives(tmp_path):
    import gzip

    s = Store(tmp_path)
    d = Destination(
        name="file", kind="file", rotation_mb=1, keep_archives=2
    ).model_dump()
    folder = tmp_path / "notifications"
    folder.mkdir()
    path = folder / "alerts.jsonl"
    outbox = Outbox(s)
    for i in range(3):
        path.write_text(str(i) * 1024 * 1024)
        await outbox.send(d, {"delivery_id": str(i)})
    assert gzip.decompress((folder / "alerts.jsonl.1.gz").read_bytes()).startswith(b"2")
    assert gzip.decompress((folder / "alerts.jsonl.2.gz").read_bytes()).startswith(b"1")
    assert not (folder / "alerts.jsonl.3.gz").exists()
