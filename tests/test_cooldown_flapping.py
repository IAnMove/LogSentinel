"""A problem that comes and goes gets one alert and one recovery per cooldown window."""

from collections import Counter

from logsentinel.portal.analysis import Analyzer
from logsentinel.portal.models import Destination, Machine, Source
from logsentinel.portal.notify import enqueue
from logsentinel.portal.store import Store


def flapping_problem(tmp_path):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="A").model_dump())
    source = store.get("source", store.put("source", Source(name="app", machine_id=machine, kind="push", enabled=True).model_dump()))
    store.put("destination", Destination(name="Local", kind="file", enabled=True, min_severity="LOW", cooldown_seconds=300).model_dump())
    store.ingest(source, [dict(origin="a", message="disk 91% full", service="df")])
    event = store.events(limit=5)[0]
    finding = dict(title="Disk nearly full", summary="s", severity="HIGH", category="storage", evidence_ids=[event["id"]])
    pid = Analyzer(store).save_finding(machine, finding, [event["id"]], notify=False)
    return store, machine, pid, finding, event


def outcomes(store):
    return Counter(r["status"] for r in store.rows("deliveries"))


def test_alternating_updates_and_recoveries_do_not_escape_the_cooldown(tmp_path):
    store, machine, pid, finding, event = flapping_problem(tmp_path)
    for event_type in ("problem.updated", "problem.recovered") * 4:
        enqueue(store, pid, event_type=event_type)
    # Alert, recovery, and the recurrence after the first recovery; then quiet.
    assert outcomes(store)["pending"] == 3, outcomes(store)
    assert outcomes(store)["muted"] == 5


def test_the_recurrence_after_the_first_recovery_is_news(tmp_path):
    store, machine, pid, finding, event = flapping_problem(tmp_path)
    enqueue(store, pid)
    enqueue(store, pid, event_type="problem.recovered")
    enqueue(store, pid)
    assert outcomes(store)["pending"] == 3


def test_a_rise_in_severity_still_goes_out(tmp_path):
    store, machine, pid, finding, event = flapping_problem(tmp_path)
    enqueue(store, pid)
    enqueue(store, pid)
    assert outcomes(store)["pending"] == 1
    Analyzer(store).save_finding(machine, dict(finding, severity="CRITICAL"), [event["id"]], notify=False)
    enqueue(store, pid)
    assert outcomes(store)["pending"] == 2


def test_the_first_recovery_after_an_alert_is_delivered(tmp_path):
    store, machine, pid, finding, event = flapping_problem(tmp_path)
    enqueue(store, pid)
    enqueue(store, pid, event_type="problem.recovered")
    assert outcomes(store)["pending"] == 2
