import json

import pytest

from logsentinel.portal.analysis import Analyzer
from logsentinel.portal.monitor import Monitor
from logsentinel.portal.review_queue import ReviewQueue
from logsentinel.portal.fragments import fragment_groups
from tests.test_portal_review_queue import queue, configure


@pytest.mark.asyncio
async def test_long_original_has_partial_progress_and_recovers_exact_slices(queue):
    store, machine, source = queue
    configure(store, input_budget=1200, adaptive_batching=False, max_calls=1, verification="manual")
    original = "prefix " + "á\n" * 6000 + " No space left on device"
    store.ingest(source, [dict(origin="long", message=original, service="app")])
    analyzer = Analyzer(store)
    sent = []
    async def clean(payload, **kw):
        sent.append(payload["groups"][0])
        return {"findings": []}
    analyzer.client.call = clean
    await analyzer.cycle()
    state = Monitor(store, analyzer, True).state()["coverage"]
    assert state["covered"] == 0
    assert state["fragments"]["completed"] == 1
    assert state["fragments"]["total"] > 1
    # Detector does not need the part containing the tail to reach the model.
    assert any(json.loads(p["data"])["reasoning"] == "disk_full" for p in store.rows("problems"))
    store.recover()
    analyzer = Analyzer(store)
    analyzer.client.call = clean
    for _ in range(100):
        if store.events()[0]["status"] == "compact":
            break
        await analyzer.cycle()
    assert store.events()[0]["status"] == "compact"
    assert store.events()[0]["message"] == original
    sent.sort(key=lambda g: g["fragment"]["start"])
    assert "".join(g["message"] for g in sent) == original
    assert len(sent) == state["fragments"]["total"]
    assert all(a["fragment"]["end"] == b["fragment"]["start"] for a, b in zip(sent, sent[1:]))


def test_fragment_redaction_happens_before_cutting(queue):
    store, machine, source = queue
    secret = "synthetic-credential-must-never-be-split"
    store.ingest(source, [dict(origin="long", message="x" * 500 + secret + "z" * 1000)])
    groups = fragment_groups(store.events()[0], 900, (secret,))
    assert len(groups) > 1
    assert secret not in "".join(g["message"] for g in groups)
    assert "synthetic-credential" not in json.dumps(groups)


def test_cancelling_one_fragment_reschedules_all_unfinished_parts(queue):
    store, machine, source = queue
    cfg = configure(store, input_budget=1000, adaptive_batching=False)
    store.ingest(source, [dict(origin="long", message="x" * 10000)])
    worker = ReviewQueue(Analyzer(store))
    work, _ = worker.prepare(machine, cfg, 0)
    worker.cancel(work[0], work[1], "Configuration changed")
    assert store.events()[0]["status"] == "pending"
    assert all(j["status"] == "cancelled" for j in store.rows("jobs"))
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM review_parts").fetchone()[0] == 0
