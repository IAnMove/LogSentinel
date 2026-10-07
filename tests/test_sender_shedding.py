"""Past its resume mark, a sender counts routine repeats instead of storing them, and says so later."""

import pytest

from logsentinel.portal.sender_safety import CaptureGate, SenderLimits
from logsentinel.portal.store import Store

SENDER = {"id": "sender", "machine_id": "sender"}


def routine(n):
    return dict(origin=f"r{n}", message=f"Started Session {n} of user ina.", service="systemd")


def test_routine_repeats_are_counted_not_stored_while_shedding(tmp_path):
    store = Store(tmp_path)
    store.prepare_sender()
    store.ingest(SENDER, [routine(n) for n in range(120)])  # the shape becomes routine
    store.shed_routine = True
    store.ingest(SENDER, [routine(n) for n in range(120, 170)] + [
        dict(origin="oom", message="Out of memory: Killed process 1 (java)", service="kernel", priority=2),
        dict(origin="rare", message="disk write failed on block 7", service="app"),
    ])
    messages = {e["origin"] for e in store.events(limit=1000)}
    assert "oom" in messages and "rare" in messages
    assert "r169" not in messages and "r119" in messages
    assert store.sender_pending() == 122
    assert len(store.events(limit=1000)) == 122


def test_a_summary_line_per_shape_is_stored_once_the_spool_recovers(tmp_path):
    store = Store(tmp_path)
    store.prepare_sender()
    store.ingest(SENDER, [routine(n) for n in range(120)])
    store.shed_routine = True
    store.ingest(SENDER, [routine(n) for n in range(120, 170)])
    store.shed_routine = False
    assert store.flush_shed(SENDER) == 1
    summary = [e for e in store.events(limit=1000) if e["origin"].startswith("shed:")]
    assert len(summary) == 1
    assert "50 routine lines like this were not stored" in summary[0]["message"]
    assert "Started Session" in summary[0]["message"] and summary[0]["metadata"]["shed"] == 50
    assert store.flush_shed(SENDER) == 0, "flushed once"
    assert store.sender_pending() == 121


def test_without_the_flag_nothing_is_shed(tmp_path):
    store = Store(tmp_path)
    store.ingest(SENDER, [routine(n) for n in range(170)])
    assert len(store.events(limit=1000)) == 170


def test_a_central_source_never_sheds(tmp_path):
    store = Store(tmp_path)
    store.shed_routine = True
    store.ingest({"id": "s1", "machine_id": "m"}, [routine(n) for n in range(170)])
    assert len(store.events(limit=1000)) == 170


class FakeStore:
    def __init__(self, pending, used=0, quota=1000):
        self.pending, self.used, self.quota = pending, used, quota

    def storage_usage(self):
        return dict(used_bytes=self.used, quota_bytes=self.quota, disk_free_bytes=10**12)

    def sender_pending(self):
        return self.pending


@pytest.mark.parametrize("pending, shedding, stops", [(100, False, False), (70_000, True, False), (100_000, False, True)])
def test_the_gate_sheds_between_the_marks_and_stops_at_high_water(monkeypatch, pending, shedding, stops):
    from logsentinel.portal import sender_safety

    monkeypatch.setattr(sender_safety, "io_pressure", lambda: None)
    gate = CaptureGate(FakeStore(pending), SenderLimits())
    if stops:
        with pytest.raises(sender_safety.SenderWait):
            gate.check()
    else:
        gate.check()
    assert gate.shedding is shedding


def test_shedding_can_be_switched_off_in_the_limits(monkeypatch):
    from logsentinel.portal import sender_safety

    monkeypatch.setattr(sender_safety, "io_pressure", lambda: None)
    gate = CaptureGate(FakeStore(70_000), SenderLimits(shed_routine=False))
    gate.check()
    assert gate.shedding is False


def test_delivery_takes_urgent_then_the_rarest_then_the_oldest(tmp_path):
    store = Store(tmp_path)
    store.ingest(SENDER, [routine(n) for n in range(150)])
    store.ingest(SENDER, [dict(origin="rare", message="disk write failed on block 7", service="app")])
    store.ingest(SENDER, [dict(origin="oom", message="Out of memory: Killed process 1 (java)", service="kernel", priority=2)])
    picked = [e["origin"] for e in store.pending_for_delivery(4)]
    # The first sighting of the routine shape also ranks as rare, and is older.
    assert picked == ["oom", "r0", "rare", "r1"]
