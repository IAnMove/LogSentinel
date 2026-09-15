"""Regressions for paused receivers, saturated legacy queues and slow storage."""

import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
import sqlite3
import sys

import httpx
import pytest
from fastapi.testclient import TestClient

from logsentinel.portal.collect import Collector
from logsentinel.portal.forward import forward
from logsentinel.portal.ingest import create_ingest_app
from logsentinel.portal.journal_stream import read_journal
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.sender import run_workers, status
from logsentinel.portal.sender_safety import (
    CaptureGate,
    SenderLimits,
    SenderWait,
    error_detail,
)
from logsentinel.portal.store import Store


@pytest.fixture
def receiver(tmp_path, monkeypatch):
    store = Store(tmp_path / "receiver")
    machine = store.put("machine", Machine(name="Synthetic host").model_dump())
    sid = store.put(
        "source",
        Source(
            name="Synthetic logs", machine_id=machine, kind="push", enabled=True
        ).model_dump(),
    )
    store.set_meta("push:" + sid, hashlib.sha256(b"synthetic").hexdigest())
    app = create_ingest_app(store)
    real = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: real(
            transport=httpx.ASGITransport(app=app),
            **{k: v for k, v in kwargs.items() if k != "transport"},
        ),
    )
    monkeypatch.setattr("logsentinel.portal.sender_safety.io_pressure", lambda: 0)
    return store, machine, sid, app


@pytest.mark.asyncio
async def test_pause_retains_cursor_and_ids_without_capture_then_explicit_resume(
    receiver, tmp_path, monkeypatch
):
    store, machine, sid, app = receiver
    path = tmp_path / "logs"
    path.write_text("first\n")
    spool = tmp_path / "spool"
    await forward(str(path), "http://localhost", sid, "synthetic", spool, once=True)
    queue = Store(spool)
    cursor = queue.cursor("sender", str(path))
    queue.ingest(
        queue.get("source", "sender"), [dict(origin="buffered", message="buffered")]
    )
    ids = [e["id"] for e in queue.events()]
    data = store.get("machine", machine)
    data.pop("id")
    data["monitoring_paused"] = True
    store.put("machine", data, machine)
    path.write_text("first\nsecond\n")
    poll = Collector.poll
    monkeypatch.setattr(
        Collector,
        "poll",
        lambda *_: pytest.fail("paused receiver must prevent capture"),
    )
    for _ in range(3):
        await forward(str(path), "http://localhost", sid, "synthetic", spool, once=True)
    assert queue.cursor("sender", str(path)) == cursor
    assert [e["id"] for e in queue.events()] == ids
    assert len(store.events()) == 1
    health = json.loads(store.meta("health:" + sid))
    assert health["status"] == "paused" and health["sender_pending"] == 1
    assert health["sender"]["build"] == "1.0.1"
    with TestClient(app) as c:
        assert c.get("/sender-control/" + sid).status_code == 401
        response = c.post(
            "/ingest/" + sid,
            json={"events": [{"id": "rejected", "raw": "ignored"}]},
            headers={"Authorization": "Bearer synthetic"},
        )
        assert (
            response.status_code == 409
            and response.json()["detail"]["code"] == "machine_paused"
        )
    data["monitoring_paused"] = False
    store.put("machine", data, machine)
    monkeypatch.setattr(Collector, "poll", poll)
    await forward(str(path), "http://localhost", sid, "synthetic", spool, once=True)
    assert {e["message"] for e in store.events()} == {"first", "second", "buffered"}
    assert queue.sender_pending() == 0 and queue.events() == []


def test_legacy_queue_indexed_cleanup_reuses_pages_without_vacuum(
    tmp_path, monkeypatch
):
    store = Store(tmp_path)
    source = dict(
        Source(
            name="legacy", machine_id="sender", kind="journald", enabled=True
        ).model_dump(),
        id="sender",
    )
    store.put("source", {k: v for k, v in source.items() if k != "id"}, "sender")
    # Incompressible synthetic content exercises real free-page accounting.
    for batch in range(10):
        store.ingest(
            source,
            [
                dict(origin=f"{batch}-{i}", message=os.urandom(6000).hex())
                for i in range(20)
            ],
            "journal",
            {"cursor": str(batch)},
        )
    store.prepare_sender()
    assert store.sender_pending() == 200
    commands = []
    connect = store.connect

    @contextmanager
    def traced():
        with connect() as db:
            db.set_trace_callback(commands.append)
            yield db

    monkeypatch.setattr(store, "connect", traced)
    rows = store.events(limit=200)
    store.mark([e["id"] for e in rows[:10]], "sent")
    assert store.discard_sent([e["id"] for e in rows[:10]]) == 0
    store.mark([e["id"] for e in rows[10:]], "sent")
    assert store.discard_sent([e["id"] for e in rows]) == 10
    usage = store.storage_usage()
    assert usage["reusable_bytes"] > 1000000
    assert store.sender_pending() == 0
    assert not any("VACUUM" in q.upper() for q in commands)
    assert store.cursor("sender", "journal") == {"cursor": "9"}
    before = usage["allocated_bytes"]
    for batch in range(10):
        store.ingest(
            source,
            [
                dict(origin=f"new-{batch}-{i}", message=os.urandom(6000).hex())
                for i in range(20)
            ],
        )
    assert store.size() < before + 1024 * 1024
    assert Store(tmp_path).sender_pending() == 200
    with store.connect() as db:
        plan = " ".join(
            str(tuple(r))
            for r in db.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM segments WHERE NOT EXISTS(SELECT 1 FROM events WHERE segment_id=segments.id AND status!='sent')"
            )
        )
    assert "events_segment" in plan and "SCAN events" not in plan


def test_capture_hysteresis_and_io_guard_allow_bounded_drain(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.prepare_sender()
    usage = dict(
        allocated_bytes=900,
        used_bytes=860,
        reusable_bytes=40,
        quota_bytes=1000,
        disk_free_bytes=2**30,
    )
    monkeypatch.setattr(store, "storage_usage", lambda: usage)
    monkeypatch.setattr("logsentinel.portal.sender_safety.io_pressure", lambda: 0)
    gate = CaptureGate(store, SenderLimits())
    with pytest.raises(SenderWait, match="queue_high_water"):
        gate.check()
    gate.check(delivery=True)

    usage["used_bytes"] = 700
    with pytest.raises(SenderWait, match="queue_high_water"):
        gate.check()
    usage["used_bytes"] = 590
    gate.check()
    monkeypatch.setattr("logsentinel.portal.sender_safety.io_pressure", lambda: 99)
    with pytest.raises(SenderWait, match="disk_io_pressure"):
        gate.check()
    with pytest.raises(SenderWait, match="disk_io_pressure"):
        gate.check(delivery=True)
    monkeypatch.setattr("logsentinel.portal.sender_safety.io_pressure", lambda: None)
    usage["disk_free_bytes"] = 100 * 1024**2
    with pytest.raises(SenderWait, match="disk_free_reserve"):
        gate.check()
    gate.check(delivery=True)


def test_reusable_pages_admit_new_logs_even_if_physical_file_exceeds_quota(tmp_path):
    store = Store(tmp_path)
    with store.connect() as db:
        db.execute("CREATE TABLE obsolete(payload BLOB)")
        db.execute("INSERT INTO obsolete VALUES(zeroblob(36000000))")
    with store.connect() as db:
        db.execute("DROP TABLE obsolete")
    cfg = store.settings()
    cfg.disk_limit_mb = 32
    store.set_meta("settings", cfg.model_dump_json())
    assert store.size() > 32 * 1024**2
    assert (
        store.ingest(
            {"id": "sender", "machine_id": "sender"},
            [dict(origin="new", message="retained")],
        )
        == 1
    )


def test_status_is_coalesced_and_sqlite_failure_does_not_cascade(
    tmp_path, monkeypatch, caplog
):
    store = Store(tmp_path)
    writes = []
    write = store.set_meta
    monkeypatch.setattr(
        store, "set_meta", lambda k, v: (writes.append((k, v)), write(k, v))
    )
    for _ in range(100):
        status(store, "capture", True)
    assert len(writes) == 1
    status(store, "capture", False, "suspended", code="queue_full")
    assert len(writes) == 2 and json.loads(writes[-1][1])["last_success"]

    def failure(*_):
        raise sqlite3.OperationalError("private SQL/token must never appear")

    monkeypatch.setattr(store, "set_meta", failure)
    status(store, "capture", False, "suspended", code="SQLITE_BUSY")
    assert "private SQL" not in caplog.text


@pytest.mark.asyncio
async def test_sqlite_and_quota_capture_errors_back_off_without_restart(
    tmp_path, monkeypatch
):
    store = Store(tmp_path)
    delays = []
    attempts = []

    async def capture():
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("Storage quota reached; incoming data was not acknowledged")
        raise sqlite3.OperationalError("database is locked")

    async def deliver():
        await asyncio.Event().wait()

    async def sleep(seconds):
        delays.append(round(seconds))
        if len(delays) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await run_workers(capture, deliver, 2, store, False)
    assert delays == [30, 60, 120] and len(attempts) == 3


def test_journal_stream_is_bounded_without_disk_temporaries(monkeypatch):
    import tempfile

    monkeypatch.setattr(
        tempfile,
        "TemporaryFile",
        lambda *_a, **_k: pytest.fail("journal must not spool to disk"),
    )
    code = "import os; os.write(2,b'x'*20000);\nwhile True: os.write(1,b'log\\n'*16384)"
    output, limited = read_journal([sys.executable, "-c", code], 8192)
    assert limited and len(output) == 8192


def test_missing_journal_cursor_is_visible_and_never_advanced(tmp_path, monkeypatch):
    store = Store(tmp_path)
    source = dict(
        Source(
            name="journal", machine_id="sender", kind="journald", enabled=True
        ).model_dump(),
        id="sender",
    )
    store.ingest(source, [], "journal", {"cursor": "old"})
    monkeypatch.setattr(
        "logsentinel.portal.collect.read_journal",
        lambda *_: (b'{"__CURSOR":"new","MESSAGE":"after rotation"}\n', False),
    )
    with pytest.raises(ValueError, match="retention gap"):
        Collector(store).poll(source, True)
    assert store.cursor("sender", "journal") == {"cursor": "old"} and not store.events()


def test_large_inclusive_cursor_does_not_starve_next_record(tmp_path, monkeypatch):
    store = Store(tmp_path)
    source = dict(
        Source(
            name="journal",
            machine_id="sender",
            kind="journald",
            enabled=True,
            max_batch_bytes=1024,
        ).model_dump(),
        id="sender",
    )
    store.ingest(source, [], "journal", {"cursor": "old"})
    old = json.dumps(dict(__CURSOR="old", MESSAGE="x" * 900)).encode() + b"\n"
    new = json.dumps(dict(__CURSOR="new", MESSAGE="y" * 400)).encode() + b"\n"
    assert len(old) < 1024 and len(old + new) > 1024
    monkeypatch.setattr(
        "logsentinel.portal.collect.read_journal",
        lambda command, limit: ((old + new)[:limit], len(old + new) >= limit),
    )
    assert Collector(store).poll(source, True) == 1
    assert store.cursor("sender", "journal") == {"cursor": "new"}
    assert store.events()[0]["message"] == "y" * 400


@pytest.mark.parametrize(
    "number,expected",
    [
        (401, "authentication_failed"),
        (429, "receiver_quota"),
        (507, "receiver_storage_full"),
    ],
)
def test_diagnostics_do_not_echo_remote_bodies(number, expected):
    request = httpx.Request(
        "POST",
        "https://localhost/ingest/source",
        headers={"Authorization": "Bearer private"},
    )
    response = httpx.Response(
        number, json={"detail": "private log/credential"}, request=request
    )
    assert error_detail(
        httpx.HTTPStatusError("private", request=request, response=response)
    ) == dict(code=expected, http_status=number)
