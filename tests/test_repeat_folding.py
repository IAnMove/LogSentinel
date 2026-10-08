"""Thousands of routine lines that differ only in a number cost one model call, not ten."""

import pytest

from logsentinel.portal.analysis import Analyzer
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store


def host(tmp_path):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="A").model_dump())
    source = store.get("source", store.put("source", Source(name="app", machine_id=machine, kind="push", enabled=True).model_dump()))
    return store, source


@pytest.mark.asyncio
async def test_thousands_of_routine_repeats_are_one_counted_group_in_one_call(tmp_path):
    store, source = host(tmp_path)
    # 4 500 repeats and one other line: a batch holds at most the 5 000 rows the store reads at once.
    for batch in range(9):
        store.ingest(source, [dict(origin=f"s{batch}-{n}", message=f"Started Session {batch * 500 + n} of user ina.", service="systemd") for n in range(500)])
    store.ingest(source, [dict(origin="odd", message="disk write failed on block 7", service="app")])
    analyzer = Analyzer(store)
    calls = []

    async def model(payload, **kwargs):
        calls.append(payload["groups"])
        return {"findings": []}

    analyzer.client.call = model
    await analyzer.cycle()
    assert len(calls) == 1, f"{len(calls)} calls for one routine shape"
    groups = calls[0]
    session = next(g for g in groups if g["message"].startswith("Started Session"))
    assert session["count"] == 4500
    assert "#" in session["message"] and len(session.get("examples", [])) == 2
    assert any(g["message"].startswith("disk write failed") for g in groups)
    assert {e["status"] for e in store.events(limit=6000)} == {"compact"}


@pytest.mark.asyncio
async def test_distinct_lines_are_still_reviewed_one_by_one(tmp_path):
    store, source = host(tmp_path)
    # Twenty shapes seen twenty times each: not yet routine, so each is its own group.
    words = "alpha bravo charlie delta echo foxtrot golf hotel india juliet kilo lima mike november oscar papa quebec romeo sierra tango".split()
    for repeat in range(20):
        store.ingest(source, [dict(origin=f"d{w}-{repeat}", message=f"event {w} happened at {repeat}", service="app") for w in words])
    analyzer = Analyzer(store)
    calls = []

    async def model(payload, **kwargs):
        calls.append(payload["groups"])
        return {"findings": []}

    analyzer.client.call = model
    await analyzer.cycle()
    assert len({g["message"].split()[1] for g in calls[0]}) == 20, "every kind is its own group"


@pytest.mark.asyncio
async def test_the_fold_is_bounded(tmp_path):
    store, source = host(tmp_path)
    for batch in range(30):
        store.ingest(source, [dict(origin=f"s{batch}-{n}", message=f"Started Session {batch * 500 + n} of user ina.", service="systemd") for n in range(500)])
    analyzer = Analyzer(store)
    calls = []

    async def model(payload, **kwargs):
        calls.append(sum(g["count"] for g in payload["groups"]))
        return {"findings": []}

    analyzer.client.call = model
    await analyzer.cycle()
    assert calls[0] <= 5000, "one batch never exceeds what the store reads at once"
