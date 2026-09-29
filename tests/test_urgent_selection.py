"""Errors and worse are reviewed before routine lines when the backlog exceeds a batch."""

import pytest

from logsentinel.portal.analysis import Analyzer
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.review_queue import ReviewQueue, URGENT_SHARE
from logsentinel.portal.store import Store


@pytest.fixture
def queue(tmp_path):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="Test host").model_dump())
    sid = store.put("source", Source(name="Test logs", machine_id=machine, kind="push").model_dump())
    return store, store.get("machine", machine), store.get("source", sid)


def configure(store, **changes):
    cfg = store.settings().model_copy(update=changes)
    store.set_meta("settings", cfg.model_dump_json())
    return cfg


def selected_messages(store, machine, cfg):
    work, _ = ReviewQueue(Analyzer(store)).prepare(machine, cfg, 0)
    batch = work[1]
    by_id = {e["id"]: e["message"] for e in store.events(limit=5000)}
    return [by_id[i] for i in batch["selected"]]


def test_priority_zero_to_three_is_marked_urgent_at_ingest(queue):
    store, machine, source = queue
    store.ingest(source, [
        dict(origin="a", message="emergency", priority=0),
        dict(origin="b", message="error", priority=3),
        dict(origin="c", message="warning", priority=4),
        dict(origin="d", message="no priority"),
        dict(origin="e", message="odd priority", priority="3"),
    ])
    with store.connect() as db:
        marks = dict(db.execute("SELECT origin,urgent FROM events"))
    assert marks == {"a": 1, "b": 1, "c": 0, "d": 0, "e": 0}


def test_a_critical_line_is_not_stuck_behind_older_routine_lines(queue):
    store, machine, source = queue
    cfg = configure(store, max_events=10)
    store.ingest(source, [dict(origin=f"r{i}", message=f"routine event number {i}", priority=6) for i in range(30)])
    store.ingest(source, [dict(origin=f"u{i}", message=f"disk error urgent {i}", priority=3) for i in range(3)])
    chosen = selected_messages(store, machine, cfg)
    assert len(chosen) == 10
    assert sum("urgent" in m for m in chosen) == 3  # all three, although they arrived last


def test_urgent_lines_cannot_starve_routine_ones(queue):
    store, machine, source = queue
    cfg = configure(store, max_events=20)
    store.ingest(source, [dict(origin=f"u{i}", message=f"urgent burst {i}", priority=2) for i in range(40)])
    store.ingest(source, [dict(origin=f"r{i}", message=f"routine burst {i}", priority=6) for i in range(40)])
    chosen = selected_messages(store, machine, cfg)
    urgent = sum("urgent" in m for m in chosen)
    assert len(chosen) == 20
    assert urgent == int(20 * URGENT_SHARE) and len(chosen) - urgent == 20 - urgent > 0


def test_spare_room_goes_to_urgent_lines_when_no_routine_ones_wait(queue):
    store, machine, source = queue
    cfg = configure(store, max_events=12)
    store.ingest(source, [dict(origin=f"u{i}", message=f"urgent only {i}", priority=1) for i in range(30)])
    assert len(selected_messages(store, machine, cfg)) == 12


def test_without_urgent_lines_order_is_unchanged(queue):
    store, machine, source = queue
    cfg = configure(store, max_events=10)
    store.ingest(source, [dict(origin=f"r{i}", message=f"routine {i:02d}", priority=6) for i in range(25)])
    assert sorted(selected_messages(store, machine, cfg)) == [f"routine {i:02d}" for i in range(10)]
