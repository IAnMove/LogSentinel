import copy
import json
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from logsentinel.portal.analysis import Analyzer, IncompleteModelResponse
from logsentinel.portal.batch_budget import batch_budget, profile_key
from logsentinel.portal.compaction import compact, public_group
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.monitor import Monitor
from logsentinel.portal.public_static import PublicStaticFiles
from logsentinel.portal.review_queue import ReviewQueue
from logsentinel.portal.store import Store, dumps
from tests.test_portal_api import client, machine_source


@pytest.fixture
def queue(tmp_path):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="Test host").model_dump())
    sid = store.put(
        "source", Source(name="Test logs", machine_id=machine, kind="push").model_dump()
    )
    return store, store.get("machine", machine), store.get("source", sid)


def configure(store, **changes):
    cfg = store.settings().model_copy(update=changes)
    store.set_meta("settings", cfg.model_dump_json())
    return cfg


def ingest(store, source, count, prefix="line"):
    store.ingest(
        source,
        [
            dict(origin=f"{prefix}-{i}", message=f"{prefix}-{i}", service="app")
            for i in range(count)
        ],
    )


@pytest.mark.asyncio
async def test_multiple_batches_drain_history_and_never_discard_overflow(queue):
    store, machine, source = queue
    configure(store, max_events=10, max_calls=3)
    ingest(store, source, 37)
    with store.connect() as db:
        db.execute(
            "UPDATE events SET status='capacity',received=?", (time.time() - 1000,)
        )
    analyzer = Analyzer(store)
    sizes = []

    async def clean(payload, **kwargs):
        sizes.append(sum(g["count"] for g in payload["groups"]))
        return {"findings": []}

    analyzer.client.call = clean
    assert await analyzer.cycle() == {"calls": 3, "errors": 0}
    assert sizes == [10, 10, 10]
    state = Monitor(store, analyzer, True).state()["coverage"]
    assert state["covered"] == state["history_recovered"] == 30
    assert state["queued"] == state["history_remaining"] == 7
    await analyzer.cycle()
    assert len(store.events(status="compact")) == 37
    assert not store.events(status="capacity")


@pytest.mark.asyncio
async def test_retry_after_restart_uses_frozen_payload_and_original_ids(queue):
    store, machine, source = queue
    configure(store, max_calls=1, input_budget=800)
    ingest(store, source, 10)
    store.ingest(
        source, [dict(origin="disk", message="rare disk failure", service="kernel")]
    )
    analyzer = Analyzer(store)
    requests = []

    async def flaky(payload, **kwargs):
        requests.append(copy.deepcopy(payload))
        if len(requests) == 1:
            raise TimeoutError("synthetic timeout")
        return {"findings": []}

    analyzer.client.call = flaky
    await analyzer.cycle()
    assert any(g["service"] == "kernel" for g in requests[0]["groups"])
    first = store.rows("jobs")[0]
    with store.connect() as db:
        frozen = json.loads(db.execute("SELECT data FROM review_batches").fetchone()[0])
    ingest(store, source, 5, "new")
    store.recover()
    restored = Analyzer(store)
    restored.client.call = flaky
    await restored.cycle()
    assert requests[0] == requests[1]
    assert store.rows("jobs")[0]["event_ids"] == first["event_ids"]
    assert {e["id"] for e in store.events(status="compact")} == set(frozen["selected"])
    assert all(
        e["status"] == "pending"
        for e in store.events()
        if e["origin"].startswith("new")
    )


@pytest.mark.asyncio
async def test_frozen_success_is_materialized_without_repeating_model_call(queue):
    store, machine, source = queue
    cfg = configure(store, max_calls=1)
    ingest(store, source, 3)
    analyzer = Analyzer(store)
    work, _ = ReviewQueue(analyzer).prepare(machine, cfg, 0)
    job, batch, _ = work
    batch.update(phase="triage_done", result={"findings": []})
    ReviewQueue(analyzer).save(job, batch)

    async def forbidden(*args, **kwargs):
        raise AssertionError("Successful frozen result must not call the model again")

    analyzer.client.call = forbidden
    assert await analyzer.cycle() == {"calls": 0, "errors": 0}
    assert len(store.events(status="compact")) == 3


@pytest.mark.asyncio
async def test_incomplete_reply_splits_exact_original_groups(queue):
    store, machine, source = queue
    configure(store, max_calls=3)
    ingest(store, source, 4)
    analyzer = Analyzer(store)
    requests = []

    async def bounded(payload, **kwargs):
        requests.append(payload)
        if len(payload["groups"]) > 2:
            raise IncompleteModelResponse("Output limit")
        return {"findings": []}

    analyzer.client.call = bounded
    assert await analyzer.cycle() == {"calls": 3, "errors": 0}
    assert [len(p["groups"]) for p in requests] == [4, 2, 2]
    assert len(store.events(status="compact")) == 4
    assert sorted(j["status"] for j in store.rows("jobs")) == ["done", "done", "split"]


@pytest.mark.asyncio
async def test_split_failure_rolls_back_both_children(queue, monkeypatch):
    store, machine, source = queue
    cfg = configure(store, max_calls=1)
    ingest(store, source, 4)
    analyzer = Analyzer(store)
    worker = ReviewQueue(analyzer)
    work, _ = worker.prepare(machine, cfg, 0)
    original = worker.create
    children = 0

    def interrupted(*args, **kwargs):
        nonlocal children
        children += 1
        if children == 2:
            raise RuntimeError("Interrupted split transaction")
        return original(*args, **kwargs)

    worker.create = interrupted

    async def incomplete(*args, **kwargs):
        raise IncompleteModelResponse("Output limit")

    analyzer.client.call = incomplete
    with pytest.raises(RuntimeError):
        await worker.execute(machine, work)
    assert len(store.rows("jobs")) == 1
    store.recover()
    assert store.rows("jobs")[0]["status"] == "retry"


def routine(i, body=None, **changes):
    event = dict(
        id=str(i),
        source_id="s",
        service="python",
        priority=6,
        timestamp=f"2026-09-08T20:{i:02d}:00Z",
        metadata={"systemd_unit": "worker.service"},
        message=f"2026-09-08 20:{i:02d}:00,123 [INFO] httpx: "
        + (
            body or 'HTTP Request: GET https://example.invalid/health "HTTP/1.1 200 OK"'
        ),
    )
    event.update(changes)
    return event


def test_routine_templates_keep_frequency_examples_refs_and_variants():
    events = [routine(i) for i in (0, 0, 0, 2)]
    for i, event in enumerate(events):
        event["id"] = str(i)
    variants = [
        routine(3, priority=3),
        routine(4, metadata={}),
        routine(
            5,
            body='HTTP Request: GET https://example.invalid/health "HTTP/1.1 500 Error"',
        ),
        routine(
            6, body='HTTP Request: GET https://example.invalid/other "HTTP/1.1 200 OK"'
        ),
        routine(7, body="custom INFO message 2026-09-08 20:07:00"),
        routine(8, body="custom INFO message 2026-09-08 20:08:00"),
    ]
    groups, selected, omitted = compact(events + variants, 20000)
    assert len(groups) == 7 and not omitted
    group = groups[0]
    assert group["count"] == 4 and group["frequency"]["counts"] == [3, 0, 1]
    assert group["event_ids"] == ["0", "1", "2", "3"]
    assert group["examples"][0]["message"] == events[0]["message"]
    assert group["examples"][-1]["message"] == events[-1]["message"]
    assert len(dumps([public_group(g) for g in groups]).encode()) <= 20000


def test_timestamp_identifiers_in_urls_do_not_get_normalized():
    events = [
        routine(
            i,
            body=f'HTTP Request: GET https://example.invalid/reports/2026-09-08T20:0{i}:00Z "HTTP/1.1 200 OK"',
        )
        for i in (0, 1)
    ]
    assert len(compact(events, 10000)[0]) == 2


def test_retained_journald_events_recover_unit_from_original():
    events = [
        routine(
            i,
            metadata={},
            source_type="JOURNALD",
            raw=dumps({"_SYSTEMD_USER_UNIT": "worker.service"}),
        )
        for i in (0, 1)
    ]
    groups, selected, _ = compact(events, 5000)
    assert len(groups) == 1 and len(selected) == 2
    assert groups[0]["normalizer"] == "routine-dates-v1"


@pytest.mark.asyncio
async def test_every_candidate_gets_independent_verification_in_bounded_chunks(queue):
    store, machine, source = queue
    configure(store, max_calls=3)
    ingest(store, source, 7)
    analyzer = Analyzer(store)
    seen = []

    async def model(payload, **kwargs):
        if "groups" in payload:
            return {
                "findings": [
                    dict(
                        title=g["message"],
                        summary="Operation failed",
                        severity="HIGH",
                        category="application",
                        evidence_ids=[g["id"]],
                    )
                    for g in payload["groups"]
                ]
            }
        seen.append([c["candidate_id"] for c in payload["candidates"]])
        return {
            "assessments": [
                dict(
                    candidate_id=c["candidate_id"],
                    status="confirmed",
                    reason="Observed failure",
                    evidence_ids=c["evidence_ids"],
                )
                for c in payload["candidates"]
            ]
        }

    analyzer.client.call = model
    assert await analyzer.cycle() == {"calls": 3, "errors": 0}
    assert seen == [["c0", "c1", "c2", "c3"], ["c4", "c5", "c6"]]
    assert len(store.rows("problems")) == 7
    assert all(
        json.loads(p["data"])["verification_status"] == "confirmed"
        for p in store.rows("problems")
    )


@pytest.mark.asyncio
async def test_omitted_verification_candidate_is_retried_and_never_erased(queue):
    store, machine, source = queue
    configure(store, max_calls=2)
    ingest(store, source, 2)
    analyzer = Analyzer(store)

    async def model(payload, **kwargs):
        if "groups" in payload:
            return {
                "findings": [
                    dict(
                        title=g["message"],
                        summary="Operation failed",
                        severity="HIGH",
                        category="application",
                        evidence_ids=[g["id"]],
                    )
                    for g in payload["groups"]
                ]
            }
        c = payload["candidates"][0]
        return {
            "assessments": [
                dict(
                    candidate_id=c["candidate_id"],
                    status="unsupported",
                    reason="Not enough evidence",
                    evidence_ids=c["evidence_ids"],
                )
            ]
        }

    analyzer.client.call = model
    for _ in range(3):
        await analyzer.cycle()
        assert len(store.rows("problems")) == 2
        assert all(p["status"] == "open" for p in store.rows("problems"))
    assert store.rows("jobs")[0]["status"] == "partial"
    assert len(store.events(status="compact")) == 2


def test_budget_uses_same_model_profile_and_shrinks_after_slow_calls(queue):
    store, _, _ = queue
    cfg = configure(store, input_budget=8000, context_tokens=16384)
    assert batch_budget(store, cfg, 10000)["input_bytes"] == 5000
    for model, seconds in (("different-model", 100), (cfg.llm.model, 60)):
        profile = cfg.model_copy(deep=True)
        profile.llm.model = model
        store.record_usage(
            "",
            "",
            [],
            "analysis",
            time.monotonic() - seconds,
            100,
            50,
            "ok",
            dict(review_profile=profile_key(profile), batch_budget_bytes=5000),
        )
    tuned = batch_budget(store, cfg, 10000)
    assert tuned["samples"] == 1 and tuned["input_bytes"] == 3750
    assert tuned["reason"] == "slow_batch"


def test_cold_load_does_not_reduce_the_log_input_budget(queue):
    store, _, _ = queue
    cfg = configure(store, input_budget=12000, context_tokens=16384)
    store.record_usage(
        "",
        "",
        [],
        "analysis",
        time.monotonic() - 66,
        2000,
        11,
        "ok",
        dict(review_profile=profile_key(cfg), batch_budget_bytes=5000, load_seconds=63),
    )
    tuned = batch_budget(store, cfg, 12000)
    assert tuned["input_bytes"] == 5000
    assert 2.9 < tuned["median_work_seconds"] < 3.5


def test_recovery_api_schedules_more_than_500_without_rewinding_covered_logs(client):
    c, store = client
    machine, sid = machine_source(c)
    ingest(store, store.get("source", sid), 700)
    events = store.events(limit=1000)
    store.mark([e["id"] for e in events[:50]], "compact")
    store.mark([e["id"] for e in events[50:]], "capacity")
    assert c.post("/api/reanalyze", json={"source_id": sid}).json()["scheduled"] == 650
    assert c.post("/api/reanalyze", json={"source_id": sid}).json()["scheduled"] == 0
    assert len(store.events(status="compact")) == 50


def test_private_static_files_are_not_served_even_if_present(tmp_path):
    (tmp_path / "tutorials").mkdir()
    (tmp_path / "tutorials" / "private.html").write_text("PRIVATE")
    (tmp_path / "private.md").write_text("PRIVATE")
    (tmp_path / "tutorials.json").write_text("PRIVATE")
    (tmp_path / "app.js").write_text("'use strict';")
    app = FastAPI()
    app.mount("/static", PublicStaticFiles(directory=tmp_path))
    with TestClient(app) as c:
        for path in ("tutorials/private.html", "private.md", "tutorials.json"):
            assert c.get("/static/" + path).status_code == 404
        assert c.get("/static/app.js").status_code == 200


def test_standalone_admin_credentials_are_redacted_in_frozen_jobs(queue):
    store, machine, source = queue
    secret = store.meta("admin_token")
    store.ingest(source, [dict(origin="key", message=secret, service="logsentinel")])
    work, _ = ReviewQueue(Analyzer(store)).prepare(machine, store.settings(), 0)
    assert secret not in dumps(work[1])
    assert work[1]["payload"]["groups"][0]["message"] == "[REDACTED]"
    assert store.events()[0]["message"] == secret


def test_retention_removes_frozen_log_excerpts_and_releases_surviving_work(queue):
    store, machine, source = queue
    ingest(store, source, 3)
    worker = ReviewQueue(Analyzer(store))
    worker.prepare(machine, store.settings(), 0)
    with store.connect() as db:
        db.execute("UPDATE segments SET created=?", (time.time() - 31 * 86400,))
    store.prune()
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM review_batches").fetchone()[0] == 0
    assert store.rows("jobs")[0]["status"] == "cancelled"


def test_cleanup_without_expired_segments_commits_before_checkpoint(queue):
    store, machine, source = queue
    ingest(store, source, 3)
    ReviewQueue(Analyzer(store)).prepare(machine, store.settings(), 0)
    assert store.prune() == 0
    assert len(store.events(status="queued")) == 3
    assert store.rows("jobs")[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_third_triage_attempt_can_still_verify_and_reports_next_work(queue):
    store, machine, source = queue
    configure(store, max_calls=1, enabled=True)
    ingest(store, source, 1)
    analyzer = Analyzer(store)
    attempts = 0

    async def model(payload, **kwargs):
        nonlocal attempts
        if "groups" in payload:
            attempts += 1
            if attempts < 3:
                raise TimeoutError("synthetic timeout")
            return {
                "findings": [
                    dict(
                        title="Failure",
                        summary="Operation failed",
                        severity="HIGH",
                        category="application",
                        evidence_ids=[payload["groups"][0]["id"]],
                    )
                ]
            }
        c = payload["candidates"][0]
        return {
            "assessments": [
                dict(
                    candidate_id=c["candidate_id"],
                    status="confirmed",
                    reason="Observed failure",
                    evidence_ids=c["evidence_ids"],
                )
            ]
        }

    analyzer.client.call = model
    for _ in range(3):
        await analyzer.cycle()
    state = Monitor(store, analyzer, True).state()
    assert state["coverage"]["queued"] == 0 and state["waiting_jobs"] == 1
    assert state["next_analysis"] is not None
    await analyzer.cycle()
    assert store.rows("jobs")[0]["status"] == "done"
    assert store.rows("jobs")[0]["attempts"] == 3


@pytest.mark.asyncio
async def test_mixed_history_and_new_logs_notify_only_new_evidence(queue, monkeypatch):
    store, machine, source = queue
    ingest(store, source, 1, "history")
    with store.connect() as db:
        db.execute(
            "UPDATE events SET status='capacity',received=?", (time.time() - 1000,)
        )
    sid = store.put(
        "source",
        Source(name="Live", machine_id=machine["id"], kind="push").model_dump(),
    )
    ingest(store, store.get("source", sid), 1, "fresh")
    analyzer = Analyzer(store)
    notices = []
    monkeypatch.setattr(
        "logsentinel.portal.notify.enqueue",
        lambda store, pid: notices.append(store.problem(pid)["title"]),
    )

    async def model(payload, **kwargs):
        return {
            "findings": [
                dict(
                    title=g["message"],
                    summary="Risk",
                    severity="MEDIUM",
                    category="application",
                    evidence_ids=[g["id"]],
                )
                for g in payload["groups"]
            ]
        }

    analyzer.client.call = model
    await analyzer.cycle()
    assert notices == ["fresh-0"]
    assert len(store.rows("problems")) == 2
