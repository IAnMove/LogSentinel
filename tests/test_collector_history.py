"""Turning on "import history" after a source has started must import what it skipped."""

from collections import Counter

import pytest

from logsentinel.portal.collect import Collector
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "data")
    machine = store.put("machine", Machine(name="A").model_dump())
    path = tmp_path / "app.log"
    source = dict(
        Source(machine_id=machine, name="app", kind="file", path=str(path), enabled=True, history=False).model_dump(),
        id="s",
    )
    collector = Collector(store)
    yield store, source, path, collector
    collector.close()


def counts(store):
    return Counter(e["message"] for e in store.events(limit=1000))


def test_history_turned_on_later_imports_the_lines_that_were_skipped(setup):
    store, source, path, collector = setup
    path.write_text("old 1\nold 2\n")
    assert collector.poll(source) == 0, "without history the existing lines are not read"
    with path.open("a") as live:
        live.write("new 1\n")
    assert collector.poll(source) == 1
    source["history"] = True
    for _ in range(3):
        collector.poll(source)
    assert counts(store) == Counter({"old 1": 1, "old 2": 1, "new 1": 1})


def test_importing_the_history_happens_once(setup):
    store, source, path, collector = setup
    path.write_text("old\n")
    collector.poll(source)
    source["history"] = True
    for _ in range(3):
        collector.poll(source)
    assert collector.poll(source) == 0
    assert counts(store) == Counter({"old": 1})


def test_a_source_that_never_turns_history_on_keeps_skipping_it(setup):
    store, source, path, collector = setup
    path.write_text("old\n")
    for _ in range(3):
        collector.poll(source)
    with path.open("a") as live:
        live.write("new\n")
    collector.poll(source)
    assert counts(store) == Counter({"new": 1})


def test_a_source_that_started_with_history_is_not_read_twice_when_nothing_changes(setup):
    store, source, path, collector = setup
    source["history"] = True
    path.write_text("a\nb\n")
    collector.poll(source)
    collector.poll(source)
    assert counts(store) == Counter({"a": 1, "b": 1})
