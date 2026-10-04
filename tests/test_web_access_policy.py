"""Web requests are counted and answered by detectors; the model never reads them."""

import json

import pytest

from logsentinel.portal.analysis import Analyzer
from logsentinel.portal.collect import normalize
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store

WEB = '192.0.2.{ip} - - [10/Oct/2026:13:{minute:02d}:{second:02d} +0000] "GET /.env?error=1 HTTP/1.1" 404 153 "-" "curl/8.0"'


def web_line(n):
    return WEB.format(ip=n % 200 + 1, minute=n // 60 % 60, second=n % 60)


def build(tmp_path, **source):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="Web host").model_dump())
    sid = store.put("source", Source(name="nginx", machine_id=machine, kind="push", **source).model_dump())
    return store, store.get("source", sid)


def ingest(store, source, web=5, other=("worker crashed: error 12",)):
    lines = [web_line(n) for n in range(web)] + list(other)
    store.ingest(source, [normalize(line, "remote", f"o{i}") for i, line in enumerate(lines)])
    return store.events(limit=100)


@pytest.mark.parametrize(
    "source",
    [
        {},
        {"analysis_mode": "keywords", "trigger_terms": "error\n.env"},
        {"analysis_mode": "priority"},
    ],
)
def test_no_analysis_mode_makes_a_web_request_a_trigger(tmp_path, source):
    store, config = build(tmp_path, **source)
    events = ingest(store, config)
    triggers, skipped = Analyzer._trigger_events(events, config)
    web_ids = {e["id"] for e in events if e["service"] == "web-access"}
    assert len(web_ids) == 5
    assert web_ids <= set(skipped)
    assert not {e["id"] for e in triggers} & web_ids


def test_other_lines_in_the_same_source_are_selected_as_before(tmp_path):
    store, config = build(tmp_path)
    events = ingest(store, config)
    triggers, skipped = Analyzer._trigger_events(events, config)
    assert [e["message"] for e in triggers] == ["worker crashed: error 12"]
    assert len(skipped) == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    [{}, {"analysis_mode": "keywords", "trigger_terms": "error", "context_minutes": 5}],
)
async def test_a_review_cycle_never_puts_a_request_in_front_of_the_model(tmp_path, source):
    store, config = build(tmp_path, **source)
    ingest(store, config)
    analyzer = Analyzer(store)
    seen = []

    async def record(payload, **kwargs):
        seen.append(json.dumps(payload))
        return {"findings": []}

    analyzer.client.call = record
    await analyzer.cycle()
    sent = " ".join(seen)
    assert "worker crashed" in sent
    assert "192.0.2." not in sent and "curl/8.0" not in sent and ".env" not in sent
    statuses = {e["service"]: e["status"] for e in store.events(limit=100)}
    assert statuses["web-access"] == "sampled"
    assert any(e["status"] != "pending" for e in store.events(limit=100) if e["service"] != "web-access")


@pytest.mark.asyncio
async def test_a_source_of_only_web_requests_makes_no_model_call(tmp_path):
    store, config = build(tmp_path)
    ingest(store, config, web=40, other=())
    analyzer = Analyzer(store)
    calls = []

    async def record(payload, **kwargs):
        calls.append(payload)
        return {"findings": []}

    analyzer.client.call = record
    assert await analyzer.cycle() == {"calls": 0, "errors": 0}
    assert not calls
    assert {e["status"] for e in store.events(limit=100)} == {"sampled"}


def test_web_requests_never_enter_the_review_queue(tmp_path):
    from logsentinel.portal.monitor import Monitor

    store, config = build(tmp_path)
    ingest(store, config, web=2000, other=("worker crashed: error 12",))
    statuses = {}
    with store.connect() as db:
        statuses = dict(db.execute("SELECT status, count(*) FROM events GROUP BY status").fetchall())
    assert statuses == {"sampled": 2000, "pending": 1}
    assert Monitor(store, Analyzer(store), True).state()["coverage"]["queued"] == 1


@pytest.mark.asyncio
async def test_a_flood_of_requests_does_not_keep_an_error_waiting(tmp_path):
    store, config = build(tmp_path)
    # Far more than a cycle picks, with the only line worth reading arriving last.
    ingest(store, config, web=25000, other=("worker crashed: error 12",))
    analyzer = Analyzer(store)
    seen = []

    async def record(payload, **kwargs):
        seen.append(json.dumps(payload))
        return {"findings": []}

    analyzer.client.call = record
    assert (await analyzer.cycle())["calls"] == 1
    assert "worker crashed" in seen[0]


def test_recovering_unreviewed_logs_does_not_requeue_web_requests(tmp_path):
    from fastapi.testclient import TestClient

    from logsentinel.portal.app import create_app

    app = create_app(tmp_path, background=False)
    with TestClient(app, base_url="http://localhost") as panel:
        panel.headers["X-LogSentinel"] = "portal"
        panel.post("/login", json={"token": app.state.store.meta("admin_token")})
        machine = panel.post("/api/objects/machine", json={"name": "A"}).json()["id"]
        sid = panel.post(
            "/api/objects/source",
            json={"name": "nginx", "machine_id": machine, "kind": "push", "enabled": True},
        ).json()["id"]
        store = app.state.store
        source = store.get("source", sid)
        ingest(store, source, web=30, other=("one", "two", "three"))
        store.mark([e["id"] for e in store.events(limit=100) if e["service"] != "web-access"], "capacity")
        assert panel.post("/api/reanalyze", json={"source_id": sid}).json()["scheduled"] == 3
        with store.connect() as db:
            statuses = dict(db.execute("SELECT status, count(*) FROM events GROUP BY status").fetchall())
        assert statuses == {"sampled": 30, "pending": 3}
