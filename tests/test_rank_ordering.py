"""A line never seen before does not wait behind fifty thousand routine ones."""

import json
import time

import pytest

from logsentinel.portal.analysis import Analyzer
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store


@pytest.mark.asyncio
async def test_a_fresh_unseen_line_reaches_the_model_in_the_first_call(tmp_path):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="A").model_dump())
    source = store.get("source", store.put("source", Source(name="app", machine_id=machine, kind="push", enabled=True).model_dump()))
    for batch in range(100):
        store.ingest(source, [dict(origin=f"r{batch}-{n}", message=f"Started Session {batch * 500 + n} of user ina.", service="systemd") for n in range(500)])
    # Received in the same live window as the backlog, no syslog priority, never seen before.
    store.ingest(source, [dict(origin="rare", message="disk write failed on block 7", service="app")])
    analyzer = Analyzer(store)
    first = []

    async def model(payload, **kwargs):
        if not first:
            first.extend(g["message"] for g in payload["groups"])
        return {"findings": []}

    analyzer.client.call = model
    await analyzer.cycle()
    assert any(m.startswith("disk write failed") for m in first), "the unseen line waited behind the routine backlog"


def test_the_pick_stays_cheap_with_a_large_retained_history(tmp_path):
    from logsentinel.portal.review_queue import pick_oldest_urgent_first

    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="A").model_dump())
    source = store.get("source", store.put("source", Source(name="app", machine_id=machine, kind="push", enabled=True).model_dump()))
    for batch in range(100):
        store.ingest(source, [dict(origin=f"r{batch}-{n}", message=f"routine line kind {n % 40} value {n}", service="app") for n in range(500)])
    with store.connect() as db:
        started = time.perf_counter()
        rows = pick_oldest_urgent_first(db, machine, source["id"], "received>=?", 0, 500)
        elapsed = time.perf_counter() - started
    assert len(rows) == 500
    assert elapsed < 0.5, f"picking a batch from 50 000 rows took {elapsed:.2f}s"
