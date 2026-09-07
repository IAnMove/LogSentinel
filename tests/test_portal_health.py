import json
import time
import asyncio
import pytest

from test_portal_api import client, machine_source
from test_portal_telemetry import configured, sample
from logsentinel.portal.models import Destination
from logsentinel.portal.app import create_app
from logsentinel.portal.capacity import capacity_report


def test_quiet_sources_are_healthy_but_explicit_heartbeats_expire_and_recover(
    client, monkeypatch
):
    c, store = client
    machine, source = machine_source(c)
    health = c.app.state.health
    start = time.time()
    clock = [start]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    health.tick()
    clock[0] += 300
    assert health.tick()["state"] == "ok"  # Old clients do not promise heartbeats.
    c.post("/api/objects/source", json={"id": source, "heartbeat_timeout_seconds": 60})
    health.tick()
    clock[0] += 61
    health.tick()
    clock[0] += 31
    health.tick()
    assert len(store.rows("problems")) == 1
    p = store.rows("problems")[0]
    assert p["machine_id"] == machine and p["status"] == "open"
    store.set_meta(
        "health:" + source, json.dumps(dict(status="ok", heartbeat=clock[0]))
    )
    health.tick()
    assert store.problem(p["id"])["status"] == "resolved"
    assert len(store.problem(p["id"])["evidence"]) == 2
    assert c.get("/healthz").json() == {"status": "ok"}


def test_metrics_timeout_and_disabled_monitoring_are_not_false_recoveries(
    client, monkeypatch
):
    c, store = client
    machine, telemetry = configured(c, store)
    health = c.app.state.health
    start = time.time()
    clock = [start]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    telemetry.receive(machine, sample())
    health.tick()
    clock[0] += 181
    health.tick()
    clock[0] += 31
    health.tick()
    problem = store.rows("problems")[0]
    assert problem["machine_id"] == machine
    cfg = telemetry.data.config(machine)
    telemetry.configure(machine, cfg.model_copy(update={"enabled": False}))
    health.tick()
    assert store.problem(problem["id"])["status"] == "open"
    assert not any(c["key"] == "metrics:" + machine for c in health.state()["checks"])


def test_sustained_cpu_recovery_and_recurrence_have_one_incident_and_separate_deliveries(
    client, monkeypatch
):
    c, store = client
    machine, telemetry = configured(c, store)
    store.put(
        "destination",
        Destination(
            name="local", kind="file", enabled=True, min_severity="LOW"
        ).model_dump(),
    )
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    for n in range(3):
        telemetry.receive(machine, sample(99, ram_pct=20))
        # Many fast samples cannot simulate minutes of sustained load.
        if n == 0:
            for _ in range(5):
                clock[0] += 1
                telemetry.receive(machine, sample(99, ram_pct=20))
            assert not store.rows("problems")
        clock[0] += 60
    problems = store.rows("problems")
    cpu = next(
        p for p in problems if json.loads(p["data"])["category"] == "resources.capacity"
    )
    assert cpu["severity"] == "CRITICAL"
    telemetry.receive(machine, sample(20, ram_pct=20))
    assert store.problem(cpu["id"])["status"] == "resolved"
    for _ in range(3):
        clock[0] += 60
        telemetry.receive(machine, sample(99, ram_pct=20))
    assert store.problem(cpu["id"])["status"] == "open"
    deliveries = [
        json.loads(d["payload"])["event_type"]
        for d in store.rows("deliveries")
        if d["problem_id"] == cpu["id"] and d["status"] == "pending"
    ]
    assert deliveries.count("problem.updated") == 2
    assert deliveries.count("problem.recovered") == 1


@pytest.mark.asyncio
async def test_notification_worker_survives_unexpected_exception(tmp_path):
    app = create_app(tmp_path)
    calls = []

    async def drain():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("temporary failure")

    app.state.outbox.drain = drain
    async with app.router.lifespan_context(app):
        for _ in range(30):
            if len(calls) >= 2:
                break
            await asyncio.sleep(0.1)
        assert len(calls) >= 2
        assert app.state.store.meta("delivery_worker_error") == ""


def test_full_storage_keeps_diagnostics_visible(client, monkeypatch):
    c, store = client
    machine, _ = machine_source(c)
    health = c.app.state.health
    check = dict(
        key="storage",
        machine_id=machine,
        bad=True,
        title="Storage",
        detail={},
        severity="CRITICAL",
    )
    monkeypatch.setattr(health, "conditions", lambda: [dict(check)])
    monkeypatch.setattr(
        health, "report", lambda *a, **k: (_ for _ in ()).throw(OSError("full"))
    )
    store.set_meta(
        "health_condition:storage", json.dumps(dict(bad_since=time.time() - 100))
    )
    state = health.tick()
    assert state["state"] == "degraded"
    assert "Storage full" in state["checks"][0]["persistence_error"]


def test_capacity_diagnostics_preserve_machine_scope_and_separate_policy(client):
    c, store = client
    machine, source = machine_source(c)
    other, other_source = machine_source(c)
    store.ingest(
        store.get("source", source),
        [{"origin": str(i), "message": "entry", "service": "app"} for i in range(4)],
    )
    events = store.events(source_id=source)
    for event, status in zip(events, ("compact", "capacity", "sampled", "measured")):
        store.mark([event["id"]], status)
    store.ingest(
        store.get("source", other_source), [{"origin": "other", "message": "different"}]
    )
    result = capacity_report(store, machine)
    assert (
        result["events"],
        result["reviewed"],
        result["capacity"],
        result["policy"],
    ) == (3, 1, 1, 1)
    assert all(s["machine_id"] == machine for s in result["services"])
    assert c.get("/api/capacity?machine_id=unknown").status_code == 404


@pytest.mark.asyncio
async def test_automatic_model_failures_back_off_and_success_resets(
    client, monkeypatch
):
    c, store = client
    monitor = c.app.state.monitor
    cfg = store.settings()
    cfg.enabled = True
    store.set_meta("settings", cfg.model_dump_json())
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    results = [
        dict(calls=1, errors=1),
        dict(calls=1, errors=1),
        dict(calls=1, errors=0),
    ]

    async def cycle():
        return results.pop(0)

    monkeypatch.setattr(c.app.state.analyzer, "cycle", cycle)
    await monitor.tick()
    assert monitor.state()["retry_after"] == clock[0] + cfg.interval_seconds
    await monitor.tick()
    assert len(results) == 2
    clock[0] += cfg.interval_seconds
    await monitor.tick()
    assert monitor.state()["retry_after"] == clock[0] + cfg.interval_seconds * 2
    clock[0] += cfg.interval_seconds * 2
    await monitor.tick()
    assert monitor.state()["consecutive_failed_cycles"] == 0
