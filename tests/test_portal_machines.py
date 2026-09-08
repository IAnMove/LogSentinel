import asyncio
import time

import pytest
from test_portal_api import client, machine_source
from logsentinel.portal.telemetry_data import MetricSample, TelemetryConfig


def entry(id="one"):
    return dict(origin=id, message="panic", raw="panic", service="kernel")


def test_pause_is_scoped_preserves_settings_and_rejects_remote_receipt(
    client, monkeypatch
):
    c, s = client
    a, sa = machine_source(c)
    b, sb = machine_source(c)
    source = s.get("source", sa)
    s.ingest(source, [entry()])
    s.ingest(s.get("source", sb), [entry()])
    telemetry = c.app.state.telemetry
    telemetry.configure(a, TelemetryConfig(enabled=True))
    token = c.post(f"/api/sources/{sa}/token").json()["token"]
    metric_token = c.post(f"/api/telemetry/{a}/token").json()["token"]
    settings = s.settings().model_dump()
    assert (
        c.post(f"/api/machines/{a}/monitoring", json={"paused": True}).status_code
        == 200
    )
    assert not s.monitoring_active(a) and s.monitoring_active(b)
    assert s.settings().model_dump() == settings
    assert s.get("source", sa) == source
    assert telemetry.data.config(a).enabled
    assert c.get(f"/api/telemetry/{a}").json()["state"] == "paused"
    assert (
        c.post(
            f"/ingest/{sa}",
            headers={"Authorization": "Bearer " + token},
            json={"events": [{"id": "two", "raw": "panic"}]},
        ).status_code
        == 409
    )
    assert (
        c.post(
            f"/ingest-metrics/{a}",
            headers={"Authorization": "Bearer " + metric_token},
            json={"samples": [MetricSample(values={"ram_pct": 50}).model_dump()]},
        ).status_code
        == 409
    )
    with pytest.raises(ValueError, match="paused"):
        s.ingest(source, [entry("two")])
    calls = []

    async def reply(payload, **kwargs):
        calls.append(kwargs["machine"])
        return {"findings": []}

    monkeypatch.setattr(c.app.state.analyzer.client, "call", reply)
    asyncio.run(c.app.state.analyzer.cycle())
    assert calls == [b]
    assert s.events(machine_id=a)[0]["status"] == "pending"
    assert c.get("/api/state").json()["monitor"]["enabled_sources"] == 1
    assert (
        c.post(f"/api/machines/{a}/monitoring", json={"paused": False}).status_code
        == 200
    )
    assert s.monitoring_active(a)
    assert s.ingest(source, [entry("two")]) == 1


def test_deletion_waits_for_model_and_cascades_only_its_machine(client, tmp_path):
    c, s = client
    a, sa = machine_source(c)
    b, sb = machine_source(c)
    source = s.get("source", sa)
    s.ingest(source, [entry()])
    s.ingest(s.get("source", sb), [entry()])
    evidence = s.events(machine_id=a)[0]["id"]
    finding = c.app.state.analyzer.save_finding(
        a,
        dict(
            title="Issue",
            summary="Evidence",
            severity="HIGH",
            category="test",
            reasoning="",
            next_steps="",
        ),
        [evidence],
        notify=False,
    )
    scoped_dest = s.put(
        "destination", dict(name="scoped", kind="file", enabled=False, machine_id=a)
    )
    global_dest = s.put("destination", dict(name="global", kind="file", enabled=False))
    source_rule = s.put("rule", dict(name="source rule", source_id=sa, machine_id=""))
    global_rule = s.put("rule", dict(name="global rule", source_id="", machine_id=""))
    s.put("chat", dict(machine_id=a, question="secret text", response={}))
    s.put("investigation", dict(machine_id=a, problem_id=finding, status="queued"))
    telemetry = c.app.state.telemetry
    telemetry.configure(a, TelemetryConfig(enabled=True))
    telemetry.receive(a, MetricSample(values={"ram_pct": 20}))
    c.post(f"/api/sources/{sa}/token")
    c.post(f"/api/telemetry/{a}/token")
    s.set_meta("health_condition:source:" + sa, '{"active":true}')
    original = tmp_path / "original.log"
    original.write_text("must remain")
    backup = tmp_path / "old-backup.db"
    backup.write_text("must remain")
    preview = c.get(f"/api/machines/{a}/delete-preview").json()
    assert preview["counts"]["events"] == 1
    assert preview["counts"]["destinations"] == 1
    assert (
        c.post(
            f"/api/machines/{a}/delete", json={"confirm_name": "different"}
        ).status_code
        == 409
    )
    assert c.post(f"/api/machines/{a}/delete", json={}).status_code == 422
    lifecycle = c.app.state.lifecycle

    async def run():
        await c.app.state.analyzer.lock.acquire()
        try:
            await lifecycle.request_delete(a, "A")
            task = lifecycle.tasks[a]
            for _ in range(100):
                if lifecycle.job(a)["status"] == "waiting":
                    break
                await asyncio.sleep(0.01)
            assert lifecycle.job(a)["status"] == "waiting"
            assert s.get("machine", a)["deletion_pending"]
            assert s.events(
                machine_id=a
            )  # Evidence survives until the in-flight request ends.
        finally:
            c.app.state.analyzer.lock.release()
        await task

    asyncio.run(run())
    assert lifecycle.job(a)["status"] == "completed", lifecycle.job(a)
    assert not s.get("machine", a) and s.get("machine", b)
    assert not s.events(machine_id=a) and len(s.events(machine_id=b)) == 1
    assert not s.problem(finding)
    assert not s.get("destination", scoped_dest) and s.get("destination", global_dest)
    assert not s.get("rule", source_rule) and s.get("rule", global_rule)
    assert not s.objects("chat") and not s.objects("investigation")
    assert not s.meta("push:" + sa) and not s.meta("telemetry_token:" + a)
    assert not s.meta("health_condition:source:" + sa)
    assert not telemetry.data.latest(a)
    assert original.read_text() == backup.read_text() == "must remain"
    with pytest.raises(ValueError, match="deleted"):
        s.ingest(source, [entry("late")])
    with s.connect() as db:
        assert db.execute("SELECT count(*) FROM segments").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM appearances").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM revisions").fetchone()[0] == 0
    assert c.get(f"/api/machines/{a}/deletion").json()["status"] == "completed"


def test_confirmed_deletion_recovers_after_shutdown_while_waiting(client):
    from logsentinel.portal.app import create_app

    c, s = client
    machine, source = machine_source(c)
    s.ingest(s.get("source", source), [entry()])
    lifecycle = c.app.state.lifecycle

    async def interrupted():
        await c.app.state.analyzer.lock.acquire()
        try:
            await lifecycle.request_delete(machine, "A")
            for _ in range(100):
                if lifecycle.job(machine)["status"] == "waiting":
                    break
                await asyncio.sleep(0.01)
            await lifecycle.close()
            assert lifecycle.job(machine)["status"] == "queued"
            assert s.events(machine_id=machine)
        finally:
            c.app.state.analyzer.lock.release()

    asyncio.run(interrupted())
    restored = create_app(s.directory, background=False).state.lifecycle

    async def resume():
        restored.recover()
        await restored.tasks[machine]

    asyncio.run(resume())
    assert restored.job(machine)["status"] == "completed"
    assert not s.get("machine", machine)
