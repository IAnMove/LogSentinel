import asyncio
from datetime import datetime, timezone
import gzip
import json
import time
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from test_portal_api import client, machine_source
from logsentinel.portal.analysis import ReviewClient
from logsentinel.portal.models import Machine
from logsentinel.portal.telemetry_data import (
    LinuxSampler,
    MetricSample,
    TelemetryConfig,
)
from logsentinel.portal.problem_context import context_for, chat_system


def configured(c, s, **config):
    machine, _ = machine_source(c)
    monitor = c.app.state.telemetry
    monitor.configure(machine, TelemetryConfig(enabled=True, **config))
    return machine, monitor


def sample(value=25, observed=None, **values):
    return MetricSample(
        observed=time.time() if observed is None else observed,
        values=dict(cpu_pct=value, ram_pct=value, **values),
    )


def test_linux_sampler_uses_available_memory_cpu_deltas_and_missing_swap(
    tmp_path, monkeypatch
):
    (tmp_path / "stat").write_text("cpu  100 0 100 700 100 0 0 0 99 0\ncpu0  0\n")
    (tmp_path / "meminfo").write_text(
        "MemTotal: 1000 kB\nMemAvailable: 600 kB\nMemFree: 10 kB\nSwapTotal: 0 kB\nSwapFree: 0 kB\n"
    )
    (tmp_path / "loadavg").write_text("1 2 3 1/100 3")
    (tmp_path / "uptime").write_text("123 55")
    monkeypatch.setattr(
        "os.statvfs",
        lambda path: SimpleNamespace(
            f_blocks=100, f_bavail=10, f_frsize=1024, f_files=200, f_favail=50
        ),
    )
    collector = LinuxSampler(tmp_path)
    first = collector.sample(["/"])
    assert first.values["ram_pct"] == 40
    assert "swap_pct" not in first.values
    assert "cpu_pct" not in first.values
    assert first.values["disk_pct:/"] == 90
    assert first.values["inode_pct:/"] == 75
    (tmp_path / "stat").write_text("cpu  150 0 100 740 110 0 0 0 150 0\ncpu0  0\n")
    second = collector.sample(["/"])
    assert second.values["cpu_pct"] == 50
    assert second.values["iowait_pct"] == 10
    assert not second.errors


def test_compressed_samples_daily_extrema_and_replay_are_atomic(client):
    c, s = client
    machine, monitor = configured(c, s)
    stamp = time.time() - 300
    first = sample(10, stamp)
    assert monitor.receive(machine, first)
    assert not monitor.receive(machine, first)
    monitor.receive(machine, sample(80, stamp + 60))
    row = next(r for r in monitor.data.rollups(machine, "day") if r["key"] == "cpu_pct")
    assert (row["minimum"], row["maximum"], row["average"], row["n"]) == (10, 80, 45, 2)
    with s.connect() as db:
        data = db.execute("SELECT data FROM telemetry_samples LIMIT 1").fetchone()[0]
        assert json.loads(gzip.decompress(data))["id"] == first.id
    with pytest.raises(ValueError, match="different measurements"):
        monitor.receive(machine, first.model_copy(update={"values": {"cpu_pct": 99}}))
    assert monitor.data.latest(machine)["values"]["cpu_pct"] == 80


def test_thresholds_spikes_hysteresis_cooldown_and_evidence(client):
    c, s = client
    machine, monitor = configured(c, s)
    now = time.time()
    for i in range(3):
        monitor.receive(machine, sample(20, now - 300 + i * 60))
    monitor.receive(machine, sample(92, now - 120))
    problems = s.rows("problems")
    assert len(problems) == 2
    assert all(json.loads(p["data"])["category"] == "resources.spike" for p in problems)
    monitor.receive(machine, sample(92, now - 60))
    assert len(s.rows("problems")) == 2
    last = sample(92, now)
    monitor.receive(machine, last)
    assert len(s.rows("problems")) == 4
    monitor.receive(machine, last)
    assert all(p["count"] == 1 for p in s.rows("problems"))
    p = next(
        s.problem(p["id"])
        for p in s.rows("problems")
        if json.loads(p["data"])["category"] == "resources.capacity"
    )
    assert p["evidence"][0]["metadata"]["measurement"]["value"] == 92
    assert p["evidence"][0]["status"] == "measured"
    payload, _ = context_for(s, machine, "", "Explain", chat_system("en"), p)
    assert payload["events"][0]["metadata"]["measurement"]["value"] == 92
    monitor.receive(machine, sample(87, now + 1))
    assert any(
        a["key"].endswith(":capacity") for a in monitor.status(machine)["active_alerts"]
    )
    monitor.receive(machine, sample(84, now + 2))
    assert not monitor.status(machine)["active_alerts"]


def test_critical_capacity_is_immediate_but_stale_uploads_do_not_alert(client):
    c, s = client
    machine, monitor = configured(c, s)
    monitor.receive(machine, sample(99, time.time() - 600))
    assert not s.rows("problems")
    assert monitor.status(machine)["state"] == "stale"
    monitor.receive(machine, sample(99))
    assert len(s.rows("problems")) == 2
    assert all(p["severity"] == "CRITICAL" for p in s.rows("problems"))


def test_remote_token_binding_rotation_validation_and_replay(client):
    c, s = client
    machine, monitor = configured(c, s)
    other, _ = machine_source(c)
    token = c.post(f"/api/telemetry/{machine}/token").json()["token"]
    headers = {"Authorization": "Bearer " + token}
    body = {"samples": [sample().model_dump()]}
    endpoint = "/ingest-metrics/" + machine
    assert c.post(endpoint, json=body).status_code == 401
    assert (
        c.post("/ingest-metrics/" + other, json=body, headers=headers).status_code
        == 401
    )
    assert (
        c.post(endpoint, json=dict(body, machine_id=other), headers=headers).status_code
        == 422
    )
    assert c.post(endpoint, json=body, headers=headers).json()["accepted"] == 1
    assert c.post(endpoint, json=body, headers=headers).json()["accepted"] == 0
    assert monitor.data.latest(other) is None
    bad = {"samples": [dict(body["samples"][0], id="bad", values={"cpu_pct": 101})]}
    assert c.post(endpoint, json=bad, headers=headers).status_code == 422
    bad = {
        "samples": [dict(body["samples"][0], id="future", observed=time.time() + 1000)]
    }
    assert c.post(endpoint, json=bad, headers=headers).status_code == 400
    c.post(f"/api/telemetry/{machine}/token")
    assert c.post(endpoint, json=body, headers=headers).status_code == 401
    assert token not in c.get("/api/telemetry/" + machine).text


def test_one_local_identity_and_collection_during_llm_lock(client, monkeypatch):
    c, s = client
    monitor = c.app.state.telemetry
    first = s.put("machine", Machine(name="Local", kind="local").model_dump())
    second = s.put("machine", Machine(name="Duplicate", kind="local").model_dump())
    remote = s.put("machine", Machine(name="Remote").model_dump())
    cfg = TelemetryConfig(enabled=True, mode="local")
    monitor.configure(first, cfg)
    with pytest.raises(ValueError, match="another machine"):
        monitor.configure(second, cfg)
    with pytest.raises(ValueError, match="local machine"):
        monitor.configure(remote, cfg)
    monkeypatch.setattr(monitor.sampler, "sample", lambda _: sample())

    async def capture_while_busy():
        async with c.app.state.analyzer.lock:
            await asyncio.to_thread(monitor.tick)

    c.portal.call(capture_while_busy)
    assert monitor.data.latest(first)
    assert monitor.data.latest(second) is None
    assert c.get("/api/monitor").json()["enabled_sources"] == 0


def test_trend_analysis_preserves_extrema_and_uses_shared_budget(client, monkeypatch):
    c, s = client
    machine, monitor = configured(c, s)
    now = time.time()
    for i in range(24):
        monitor.receive(machine, sample(70 if i == 10 else 10, now - (23 - i) * 3600))
    payload, _, report = monitor.trend_context(machine, 1, "en")
    assert report["input_bytes"] <= s.settings().input_budget
    assert max(w["values"]["cpu_pct"][1] for w in payload["windows"]) == 70
    assert sum(w["values"]["cpu_pct"][3] for w in payload["windows"]) == 24
    calls = []

    async def fake(self, payload, **kwargs):
        calls.append(kwargs)
        return {"answer": "A brief spike; current use is low", "metrics": ["cpu_pct"]}

    monkeypatch.setattr(ReviewClient, "call", fake)
    endpoint = f"/api/telemetry/{machine}/analyze"
    first = c.post(endpoint, json={"days": 1, "language": "en"}).json()
    assert c.post(endpoint, json={}).json()["id"] == first["id"]
    c.portal.call(monitor.analyze_tick)
    assert s.get("metric_analysis", first["id"])["status"] == "completed"
    assert len(calls) == 1 and calls[0]["kind"] == "metrics"
    assert not s.rows("problems")


def test_retention_keeps_daily_minima_and_maxima(client):
    c, s = client
    machine, monitor = configured(c, s)
    monitor.receive(machine, sample(20, time.time() - 2 * 86400))
    monitor.configure(machine, TelemetryConfig(enabled=True, retention_days=1))
    assert monitor.data.prune() == 1
    assert monitor.data.latest(machine) is None
    rows = monitor.data.rollups(machine, "day", 7)
    assert rows and all(r["minimum"] == 20 for r in rows)


def test_trends_keep_historical_cpu_when_latest_sample_is_warming_up(client):
    c, s = client
    machine, monitor = configured(c, s)
    monitor.receive(machine, sample(70, time.time() - 60, iowait_pct=3))
    monitor.receive(machine, MetricSample(values={"ram_pct": 50}))
    payload, _, _ = monitor.trend_context(machine, 1, "en")
    assert "cpu_pct" not in payload["latest"]["values"]
    assert payload["windows"][0]["values"]["cpu_pct"][:2] == [70, 70]
    assert payload["windows"][0]["values"]["iowait_pct"][:2] == [3, 3]


@pytest.mark.parametrize(
    "values",
    [
        {"cpu_pct": float("nan")},
        {"cpu_pct": float("inf")},
        {"ram_pct": -1},
        {"command": 1},
    ],
)
def test_metric_contract_rejects_invalid_values(values):
    with pytest.raises(ValidationError):
        MetricSample(values=values)


def test_real_model_structured_trend_notes_are_preserved_and_bounded():
    from logsentinel.portal.telemetry import TrendAnswer

    result = TrendAnswer.model_validate(
        {
            "answer": "Brief CPU peak",
            "metrics": ["cpu_pct"],
            "next_checks": ["Check workload", "Collect more history"],
            "incomplete_coverage": True,
        }
    )
    assert result.next_checks == "- Check workload\n- Collect more history"
    assert result.incomplete_coverage is True
    with pytest.raises(ValidationError):
        TrendAnswer(answer="x", next_checks=[{"command": "unsafe coercion"}])
    with pytest.raises(ValidationError):
        TrendAnswer(answer="x", incomplete_coverage="x" * 4001)


def test_bad_trend_citations_are_saved_as_error_and_restart_is_explicit(
    client, monkeypatch
):
    c, s = client
    machine, monitor = configured(c, s)
    monitor.receive(machine, sample())

    async def fake(self, payload, **kwargs):
        return {"answer": "Invented GPU claim", "metrics": ["gpu_pct"]}

    monkeypatch.setattr(ReviewClient, "call", fake)
    job = monitor.enqueue(machine)
    c.portal.call(monitor.analyze_tick)
    assert s.get("metric_analysis", job["id"])["status"] == "error"
    job = monitor.enqueue(machine)
    monitor.save_job(job, status="running")
    monitor.recover()
    assert s.get("metric_analysis", job["id"])["status"] == "interrupted"


@pytest.mark.asyncio
async def test_remote_sender_recovers_lost_ack_and_binds_spool(tmp_path, monkeypatch):
    import hashlib
    import httpx
    from logsentinel.portal.app import create_app
    from logsentinel.portal.telemetry_forward import forward_metrics
    from logsentinel.portal.store import Store

    app = create_app(tmp_path / "receiver", background=False)
    store = app.state.store
    machine = store.put("machine", Machine(name="Remote").model_dump())
    app.state.telemetry.configure(machine, TelemetryConfig(enabled=True))
    store.set_meta(
        "telemetry_token:" + machine, hashlib.sha256(b"synthetic").hexdigest()
    )
    monkeypatch.setattr(LinuxSampler, "sample", lambda self, paths: sample())
    original = httpx.AsyncClient
    transport = httpx.ASGITransport(app=app)

    class LostAck(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            await transport.handle_async_request(request)
            raise httpx.ReadTimeout("ACK lost after commit")

    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=LostAck(), **kw)
    )
    spool = tmp_path / "spool"
    with pytest.raises(RuntimeError, match="retained"):
        await forward_metrics(
            "http://localhost", machine, "synthetic", spool, once=True
        )
    assert app.state.telemetry.status(machine)["retained_samples"] == 1
    assert len(Store(spool).events()) == 1
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda **kw: original(transport=transport, **kw)
    )
    await forward_metrics("http://localhost", machine, "synthetic", spool, once=True)
    assert app.state.telemetry.status(machine)["retained_samples"] == 2
    assert not Store(spool).events()
    with pytest.raises(ValueError, match="another receiver"):
        await forward_metrics(
            "http://localhost", "other", "synthetic", spool, once=True
        )
