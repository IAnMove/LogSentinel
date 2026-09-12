import hashlib, hmac, json
import httpx
import pytest
from logsentinel.portal.store import Store
from logsentinel.portal.models import Destination
from logsentinel.portal.notify import Outbox


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result, expected",
    [
        ({"ok": True, "channel": "C123", "ts": "1"}, "delivered"),
        ({"ok": False, "error": "missing_scope"}, "chat:write"),
        ({"ok": False, "error": "not_in_channel"}, "invite"),
        ({"ok": False, "error": "invalid_auth"}, "invalid bot token"),
        ({"ok": False, "error": "xoxb-synthetic-secret"}, "Slack rejected"),
        (["xoxb-synthetic-secret"], "Slack rejected"),
    ],
)
async def test_slack_bot_contract_and_safe_failures(
    tmp_path, monkeypatch, result, expected
):
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=result)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"}),
    )
    store = Store(tmp_path)
    dest = Destination(
        name="Slack bot",
        kind="slack",
        slack_mode="bot",
        enabled=True,
        token="xoxb-synthetic-secret",
        slack_channel="C123",
        url="https://unrelated.invalid/never-use",
        headers={"Authorization": "Bearer unrelated-secret"},
    ).model_dump()
    dest["id"] = store.put("destination", dest)
    outcome = await Outbox(store).test(dest)
    request = requests[0]
    assert str(request.url) == "https://slack.com/api/chat.postMessage"
    assert request.headers["Authorization"] == "Bearer xoxb-synthetic-secret"
    assert request.headers["Content-Type"] == "application/json"
    body = json.loads(request.content)
    assert body["channel"] == "C123"
    assert body["mrkdwn"] is False
    assert "xoxb-synthetic-secret" not in request.content.decode()
    assert "unrelated-secret" not in str(request.headers)
    if expected == "delivered":
        assert outcome["status"] == "delivered"
    else:
        assert outcome["status"] == "failed"
        assert expected in outcome["error"]
    assert "xoxb-synthetic-secret" not in json.dumps(store.rows("deliveries"))


@pytest.mark.asyncio
async def test_slack_legacy_webhook_accepts_plain_text(tmp_path, monkeypatch):
    original = httpx.AsyncClient
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text="ok")

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"}),
    )
    dest = {"kind": "slack", "url": "https://synthetic.invalid/slack"}
    assert (
        await Outbox(Store(tmp_path)).send(dest, {"delivery_id": "test"}) == "delivered"
    )
    assert str(requests[0].url) == dest["url"]
    assert "Authorization" not in requests[0].headers


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
        lambda **kw: original(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"}),
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


@pytest.mark.asyncio
@pytest.mark.parametrize("failure, expected", [
    (httpx.ConnectError, "retry"),
    (httpx.ConnectTimeout, "retry"),
    (httpx.PoolTimeout, "retry"),
    (httpx.ReadTimeout, "unknown"),
    (httpx.ReadError, "unknown"),
    (httpx.WriteError, "unknown"),
    (httpx.RemoteProtocolError, "unknown"),
    (ValueError, "failed"),
])
async def test_delivery_failure_classification_and_bounded_recovery(tmp_path, failure, expected):
    from logsentinel.portal.store import dumps

    store = Store(tmp_path)
    dest = store.put("destination", Destination(
        name="Synthetic", kind="webhook", url="https://example.invalid/", enabled=True,
    ).model_dump())
    payload = dumps({"delivery_id": "same-id"})
    with store.connect() as db:
        db.execute("INSERT INTO deliveries VALUES(?,?,?,?,?,?,?,?,?,?)",
                   ("d", dest, "test", payload, "pending", 0, 0, 0, 0, None))
    outbox = Outbox(store)

    async def failed(*args):
        raise failure("synthetic")

    outbox.send = failed
    await outbox.drain()
    row = store.rows("deliveries")[0]
    assert row["status"] == expected
    assert row["attempts"] == 1
    if expected == "retry":
        store.recover()
        for _ in range(2):
            with store.connect() as db:
                db.execute("UPDATE deliveries SET next_try=0")
            await outbox.drain()
        row = store.rows("deliveries")[0]
        assert row["status"] == "failed" and row["attempts"] == 3
    assert row["payload"] == payload
