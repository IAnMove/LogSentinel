"""A healthy web source is not a coverage problem: its requests are counted apart from the real gaps."""

import time

from logsentinel.portal.analysis import Analyzer
from logsentinel.portal.capacity import capacity_report
from logsentinel.portal.collect import normalize
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.monitor import Monitor
from logsentinel.portal.store import Store
from tests.test_web_access_policy import web_line


def build(tmp_path, web=30, plain=5, priority_skipped=0):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="Web host").model_dump())
    sid = store.put("source", Source(name="nginx", machine_id=machine, kind="push", enabled=True,
                                     analysis_mode="keywords", trigger_terms="nevermatches").model_dump())
    source = store.get("source", sid)
    lines = [web_line(n) for n in range(web)] + [f"routine message {n}" for n in range(plain)]
    store.ingest(source, [normalize(text, "remote", f"o{i}") for i, text in enumerate(lines)])
    return store, machine


def test_the_monitor_counts_web_requests_separately_from_the_rest_of_the_selection(tmp_path):
    store, machine = build(tmp_path)
    analyzer = Analyzer(store)
    import asyncio

    asyncio.run(analyzer.cycle())  # keywords mode samples the 5 plain lines out as well
    coverage = Monitor(store, analyzer, True).state()["coverage"]
    assert coverage["web"] == 30
    assert coverage["policy"] == 35, "policy stays the total of what was left out by selection"
    assert coverage["policy"] - coverage["web"] == 5


def test_the_capacity_report_does_the_same_for_the_retained_history(tmp_path):
    store, machine = build(tmp_path)
    import asyncio

    asyncio.run(Analyzer(store).cycle())
    report = capacity_report(store)
    assert report["retained"]["web"] == 30
    assert report["retained"]["policy"] == 35


def test_a_machine_without_web_sources_reports_none(tmp_path):
    store, machine = build(tmp_path, web=0)
    import asyncio

    asyncio.run(Analyzer(store).cycle())
    assert Monitor(store, Analyzer(store), True).state()["coverage"]["web"] == 0
    assert capacity_report(store)["retained"]["web"] == 0
