"""Between its storage warning and its limit, the central counts routine repeats instead of storing them."""

from helpers import machine_source
from logsentinel.portal.store import Store

MiB = 1024**2


def usage(monkeypatch, used):
    monkeypatch.setattr(
        Store,
        "storage_usage",
        lambda self: dict(
            allocated_bytes=used, reusable_bytes=0, used_bytes=used, quota_bytes=1000 * MiB,
            warning_bytes=800 * MiB, reserve_bytes=0, disk_free_bytes=10**12,
        ),
    )


def routine(n):
    return dict(origin=f"r{n}", message=f"Started Session {n} of user ina.", service="systemd")


def summaries(store, sid):
    return [e for e in store.events(limit=1000) if e["source_id"] == sid and e["origin"].startswith("shed:")]


def test_routine_repeats_are_counted_above_the_warning_and_summarised_once_below_it(client, monkeypatch):
    c, store = client
    _, sid = machine_source(c)
    source = store.get("source", sid)
    usage(monkeypatch, 100 * MiB)
    assert store.ingest(source, [routine(n) for n in range(120)]) == 120, "below the mark nothing is shed"
    usage(monkeypatch, 900 * MiB)
    stored = store.ingest(source, [routine(n) for n in range(120, 170)] + [
        dict(origin="oom", message="Out of memory: Killed process 1 (java)", service="kernel", priority=2),
        dict(origin="rare", message="disk write failed on block 7", service="app"),
    ])
    assert stored == 2
    origins = {e["origin"] for e in store.events(limit=1000)}
    assert "oom" in origins and "rare" in origins and "r169" not in origins
    assert not summaries(store, sid)
    usage(monkeypatch, 100 * MiB)
    assert store.ingest(source, [routine(170)]) == 1
    summary = summaries(store, sid)
    assert len(summary) == 1
    assert "50 routine lines like this were not stored" in summary[0]["message"]
    assert "observer's storage was near its limit" in summary[0]["message"]
    assert summary[0]["metadata"]["shed"] == 50
    assert not store.meta("shed:" + sid)


def test_one_refused_summary_does_not_drop_another_sources_counts(client, monkeypatch):
    c, store = client
    _, sid_a = machine_source(c)
    _, sid_b = machine_source(c)
    source_a, source_b = store.get("source", sid_a), store.get("source", sid_b)
    usage(monkeypatch, 100 * MiB)
    store.ingest(source_a, [routine(n) for n in range(120)])
    store.ingest(source_b, [routine(n) for n in range(120)])
    usage(monkeypatch, 900 * MiB)
    store.ingest(source_a, [routine(n) for n in range(120, 130)])
    store.ingest(source_b, [routine(n) for n in range(120, 130)])
    usage(monkeypatch, 100 * MiB)
    real = Store.ingest

    def fail_a(self, source, entries, cursor_path=None, cursor=None):
        if source["id"] == sid_a and entries and str(entries[0].get("origin", "")).startswith("shed:"):
            raise OSError("Storage quota reached; incoming data was not acknowledged")
        return real(self, source, entries, cursor_path, cursor)

    monkeypatch.setattr(Store, "ingest", fail_a)
    assert store.flush_shed_pending() == 1
    assert store.meta("shed:" + sid_a) and not store.meta("shed:" + sid_b)
    assert "10 routine lines like this" in summaries(store, sid_b)[0]["message"]


def test_a_paused_machine_keeps_shed_counts_until_monitoring_resumes(client, monkeypatch):
    c, store = client
    mid, sid = machine_source(c)
    source = store.get("source", sid)
    usage(monkeypatch, 100 * MiB)
    store.ingest(source, [routine(n) for n in range(120)])
    usage(monkeypatch, 900 * MiB)
    store.ingest(source, [routine(n) for n in range(120, 130)])
    data = store.get("machine", mid)
    data.pop("id")
    data["monitoring_paused"] = True
    store.put("machine", data, mid)
    usage(monkeypatch, 100 * MiB)
    assert store.flush_shed_pending() == 0
    assert store.flush_shed(source) == 0
    assert store.meta("shed:" + sid) and not summaries(store, sid)
    data["monitoring_paused"] = False
    store.put("machine", data, mid)
    assert store.flush_shed_pending() == 1
    assert not store.meta("shed:" + sid)
    assert "10 routine lines like this" in summaries(store, sid)[0]["message"]


def test_a_quiet_source_gets_its_summary_from_the_hourly_sweep(client, monkeypatch):
    c, store = client
    _, sid = machine_source(c)
    source = store.get("source", sid)
    usage(monkeypatch, 100 * MiB)
    store.ingest(source, [routine(n) for n in range(120)])
    usage(monkeypatch, 900 * MiB)
    store.ingest(source, [routine(n) for n in range(120, 130)])
    assert store.flush_shed_pending() == 0, "still above the mark: nothing yet"
    usage(monkeypatch, 100 * MiB)
    assert store.flush_shed_pending() == 1
    assert "10 routine lines like this" in summaries(store, sid)[0]["message"]
    assert store.flush_shed_pending() == 0
