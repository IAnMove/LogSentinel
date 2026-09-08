import json
import time

import pytest

from test_portal_api import client, machine_source
from logsentinel.portal.analysis import Analyzer, SYSTEM
from logsentinel.portal.capacity import capacity_report


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
    assert (
        r["limits"]["input_ceiling_bytes"]
        == 16384 - cfg.llm.max_tokens - len(SYSTEM.encode()) - 1024
    )
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
    assert len(s.events(status="capacity")) == 1
    assert len(s.events(status="compact")) == 1
    assert not s.rows("problems")
