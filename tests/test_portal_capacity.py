import json
import time

import pytest

from test_portal_api import client, machine_source
from logsentinel.portal.analysis import Analyzer, SYSTEM
from logsentinel.portal.capacity import capacity_report, coverage_signal, recent_coverage
from logsentinel.portal.batch_budget import input_ceiling


def job(store, machine, id, created, cfg=None, status="done", attempts=1):
    with store.connect() as db:
        db.execute(
            "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,NULL)",
            (
                id,
                machine,
                "[]",
                status,
                created,
                created + 20,
                attempts,
                (cfg or store.settings()).model_dump_json(),
            ),
        )


def event(store, source, origin, received, status):
    store.ingest(
        store.get("source", source),
        [dict(origin=origin, message="test", service="app")],
    )
    with store.connect() as db:
        db.execute(
            "UPDATE events SET received=?,status=? WHERE source_id=? AND origin=?",
            (received, status, source, origin),
        )


def test_current_model_planning_excludes_previous_model_and_collecting_tail(client):
    c, s = client
    m, source = machine_source(c)
    other, osource = machine_source(c)
    now = time.time()
    cfg = s.settings()
    cfg.enabled = True
    cfg.context_tokens = 16384
    s.set_meta("settings", cfg.model_dump_json())
    with s.connect() as db:
        db.execute("UPDATE audit SET created=?", (now - 5000,))
    previous = cfg.model_copy(deep=True)
    previous.llm.model = "old-model"
    job(s, m, "old", now - 2000, previous)
    job(s, m, "a", now - 1800)
    job(s, m, "b", now - 900)
    for i, status in enumerate(
        [
            "compact",
            "reviewed",
            "capacity",
            "capacity",
            "pending",
            "error",
            "sampled",
            "excluded",
        ]
    ):
        event(s, source, str(i), now - 1000, status)
    event(s, source, "old-capacity", now - 2500, "capacity")
    event(s, source, "expired-from-hour", now - 5000, "capacity")
    event(s, source, "tail", now - 10, "pending")
    event(s, source, "metric", now - 1000, "measured")
    event(s, osource, "different-machine", now - 1000, "capacity")
    with s.connect() as db:
        for id, kind, duration in [("u1", "analysis", 10), ("u2", "investigation", 10)]:
            db.execute(
                "INSERT INTO usage VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (id, "b", m, "[]", kind, now - 880, 40, 10, duration, "ok", "{}"),
            )
        db.execute(
            "INSERT INTO usage VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                "old-usage",
                "old",
                m,
                "[]",
                "analysis",
                now - 1980,
                100,
                100,
                900,
                "error",
                "{}",
            ),
        )
    r = capacity_report(s, m)
    assert r["events"] == 10 and r["retained_capacity"] == 4
    assert r["current"]["events"] == 9
    assert r["current"]["completed_batches"] == 2
    assert r["current"]["average_batch_seconds"] == 20
    assert r["planning"]["ready"]
    assert r["planning"]["events"] == 8 and r["planning"]["pending"] == 1
    assert r["planning"]["required_multiplier"] == 3
    assert (
        r["analysis"]["calls"] == 2
        and r["analysis"]["seconds"] == 20
        and not r["analysis"]["errors"]
    )
    assert r["limits"]["effective_input_bytes"] == 5000
    assert r["limits"]["input_ceiling_bytes"] == input_ceiling(cfg, s.get("machine", m))
    assert all(x["machine_id"] == m for x in r["services"])
    # A config change starts a new measurement, not a zero-capacity verdict.
    c.post("/api/settings", json={"input_budget": 6000}).raise_for_status()
    fresh = capacity_report(s, m)
    assert not fresh["planning"]["ready"]
    assert fresh["planning"]["required_multiplier"] is None
    assert fresh["current"]["completed_batches"] == 0
    assert fresh["events"] == r["events"]
    assert "api_key" not in json.dumps(fresh)


def test_empty_paused_or_failed_model_does_not_invent_a_capacity(client):
    c, s = client
    m, source = machine_source(c)
    assert not capacity_report(s)["planning"]["ready"]
    now = time.time()
    with s.connect() as db:
        db.execute("UPDATE audit SET created=?", (now - 4000,))
    job(s, m, "failed", now - 2000, status="failed", attempts=3)
    job(s, m, "retry", now - 1000, status="done", attempts=2)
    event(s, source, "error", now - 1200, "error")
    r = capacity_report(s)
    assert not r["planning"]["ready"] and r["planning"]["required_multiplier"] is None
    assert r["current"]["completed_batches"] == 0


def test_duplicate_local_journal_is_blocked_across_machine_cards(client):
    c, s = client
    a, _ = machine_source(c)
    b, _ = machine_source(c)
    first = c.post(
        "/api/objects/source",
        json=dict(name="journal", kind="journald", machine_id=a, enabled=True),
    )
    assert first.status_code == 200
    rejected = c.post(
        "/api/objects/source",
        json=dict(name="copy", kind="journald", machine_id=b, enabled=True),
    )
    assert rejected.status_code == 409
    second = c.post(
        "/api/objects/source",
        json=dict(name="copy", kind="journald", machine_id=b, enabled=False),
    ).json()
    assert (
        c.post(
            "/api/objects/source", json=dict(id=second["id"], enabled=True)
        ).status_code
        == 409
    )
    # Legacy duplicates are diagnosed even if attached to different machine cards.
    source = s.get("source", second["id"])
    source.pop("id")
    source["enabled"] = True
    s.put("source", source, second["id"])
    assert len(capacity_report(s, a)["duplicate_journals"]) == 2
    assert (
        c.post(
            "/api/objects/source", json=dict(id=second["id"], enabled=False)
        ).status_code
        == 200
    )
    assert capacity_report(s)["duplicate_journals"] == []


def test_coverage_signal_flags_a_model_that_cannot_keep_up():
    quiet = coverage_signal(
        dict(
            events=5,
            capacity=0,
            pending=1,
            queued=0,
            incoming_per_minute=1,
            covered_per_minute=1,
        )
    )
    assert quiet["level"] == "ok"
    behind = coverage_signal(
        dict(
            events=100,
            capacity=80,
            pending=10,
            queued=0,
            incoming_per_minute=50,
            covered_per_minute=5,
        )
    )
    assert behind["level"] == "critical"
    assert behind["reason"] == "model_behind"


def test_coverage_gap_is_visible_without_failing_readiness(client):
    c, s = client
    m, source = machine_source(c)
    now = time.time()
    for i in range(40):
        event(s, source, f"cap{i}", now - 60, "capacity")
    report = capacity_report(s)
    assert report["signal"]["level"] in ("warn", "critical")
    assert recent_coverage(s)["level"] == report["signal"]["level"]
    health = c.app.state.health.tick()
    coverage = next(x for x in health["checks"] if x["key"] == "coverage")
    assert coverage["bad"] is True
    assert coverage["liveness"] is False
    assert c.get("/healthz").json()["status"] == "ok"


@pytest.mark.asyncio
async def test_old_capacity_history_does_not_create_a_new_overload_warning(client):
    c, s = client
    m, source = machine_source(c)
    event(s, source, "old", time.time() - 4000, "capacity")
    event(s, source, "new", time.time(), "pending")
    a = Analyzer(s)

    async def healthy(*args, **kwargs):
        return {"findings": []}

    a.client.call = healthy
    await a.cycle()
    assert not s.events(status="capacity")
    assert len(s.events(status="compact")) == 2
    assert not s.rows("problems")


@pytest.mark.parametrize("status", ["error", "oversized"])
@pytest.mark.parametrize("count,level", [(1, "warn"), (100, "critical")])
def test_blocked_reviews_never_show_green_even_at_low_volume(status, count, level):
    signal = coverage_signal(dict(events=count, **{status: count}, incoming_per_minute=count / 60, covered_per_minute=0))
    assert signal["level"] == level
    assert signal["reason"] == "review_blocked"
    assert signal["backlog"] == signal["blocked"] == count
    assert signal["ratio"] == 1


def test_uncovered_counts_do_not_double_count_policy_or_retry_states():
    signal = coverage_signal(dict(events=100, reviewed=10, error=10, oversized=20, queued=5, pending=5, excluded=30, policy=20))
    assert signal["backlog"] == 40
    assert signal["blocked"] == 30
    assert signal["level"] == "warn"
    clean = coverage_signal(dict(events=100, reviewed=10, excluded=70, policy=20))
    assert clean["level"] == "ok"
    assert clean["backlog"] == 0


def test_failed_and_oversized_events_show_in_api_without_breaking_liveness(client):
    c, store = client
    machine, source = machine_source(c)
    now = time.time()
    event(store, source, "failed", now - 10, "error")
    event(store, source, "large", now - 10, "oversized")
    event(store, source, "old-error", now - 4000, "error")
    report = c.get("/api/capacity").json()
    assert report["signal"]["level"] == "warn"
    assert report["signal"]["blocked"] == report["signal"]["backlog"] == 2
    assert report["error"] == report["oversized"] == 1
    check = next(c for c in c.app.state.health.tick()["checks"] if c["key"] == "coverage")
    assert check["bad"] and not check["liveness"]
    assert c.get("/healthz").status_code == 200


def test_capture_and_retained_history_follow_machine_scope_and_pause(client):
    c, store = client
    machine, source = machine_source(c)
    other, other_source = machine_source(c)
    c.post("/api/objects/source", json={"id": source, "enabled": True}).raise_for_status()
    event(store, source, "old", time.time() - 7200, "capacity")
    event(store, other_source, "other", time.time(), "compact")
    report = capacity_report(store, machine)
    assert report["capture"]["active_sources"] == 1
    assert report["capture"]["last_event"] < time.time() - 7000
    assert report["events"] == 0
    assert report["retained"]["events"] == report["retained"]["capacity"] == 1
    c.post(f"/api/machines/{machine}/monitoring", json={"paused": True}).raise_for_status()
    report = capacity_report(store, machine)
    assert report["capture"]["active_sources"] == 0
    assert report["capture"]["enabled_sources"] == 1
    assert capacity_report(store, other)["retained"]["reviewed"] == 1


def test_latency_diagnosis_needs_reported_comparable_timings():
    from logsentinel.portal.capacity import latency_breakdown

    def call(duration, status="ok", **detail):
        return dict(duration=duration, status=status, detail=json.dumps(detail))

    measured = call(100, load_seconds=80, prompt_eval_seconds=2, eval_seconds=3)
    unknown = call(100)
    invalid = call(10, load_seconds=100, prompt_eval_seconds=1, eval_seconds=1)
    assert latency_breakdown([unknown, invalid])["load_seconds"] is None
    assert not latency_breakdown([measured])["loading_dominates"]
    result = latency_breakdown([measured] * 3 + [unknown, invalid])
    assert result["loading_dominates"]
    assert result["samples"] == 3 and result["total_seconds"] == 100
    assert result["load_seconds"] == 80
    assert not latency_breakdown([call(100, "error", load_seconds=80, prompt_eval_seconds=2, eval_seconds=3)] * 3)["loading_dominates"]


def test_displayed_input_limit_matches_calibrated_queue_budget(client):
    from logsentinel.portal.batch_budget import profile_key
    from logsentinel.portal.context_budget import backend_key

    c, store = client
    machine, _ = machine_source(c)
    cfg = store.settings()
    cfg.llm.provider = "ollama"
    cfg.context_tokens = 16384
    cfg.input_budget = 40000
    store.set_meta("settings", cfg.model_dump_json())
    store.set_meta(backend_key(cfg), json.dumps(dict(checked=time.time(), rejects_truncation=True, version="0.33.2")))
    for _ in range(3):
        store.record_usage("", machine, [], "analysis", time.monotonic(), 2000, 30, "ok", dict(review_profile=profile_key(cfg), total_input_bytes=6000))
    ceiling = input_ceiling(cfg, store.get("machine", machine), store)
    report = capacity_report(store, machine)
    assert report["limits"]["input_ceiling_bytes"] == ceiling
    assert ceiling > input_ceiling(cfg, store.get("machine", machine))
    assert report["tuning"]["maximum_bytes"] == min(40000, ceiling)
