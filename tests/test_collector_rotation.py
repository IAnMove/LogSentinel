"""Rotating a log the way logrotate does must never make a line count twice."""

import gzip
import os
from collections import Counter

import pytest

from logsentinel.portal.collect import Collector
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store


@pytest.fixture
def folder(tmp_path):
    store = Store(tmp_path / "data")
    machine = store.put("machine", Machine(name="A").model_dump())
    logs = tmp_path / "logs"
    logs.mkdir()
    source = dict(
        Source(machine_id=machine, name="app", kind="folder", path=str(logs), pattern="app.log*", enabled=True, history=True).model_dump(),
        id="s",
    )
    collector = Collector(store)
    yield store, source, logs, collector
    collector.close()


def drain(collector, source):
    return sum(collector.poll(source) for _ in range(4))


def counts(store):
    return Counter(e["message"] for e in store.events(limit=1000))


def rotate_numbered(logs, keep=3):
    """logrotate's default: app.log.N becomes app.log.N+1, app.log becomes app.log.1."""
    for n in range(keep, 0, -1):
        source = logs / ("app.log" if n == 1 else f"app.log.{n - 1}")
        if source.exists():
            os.rename(source, logs / f"app.log.{n}")
    (logs / "app.log").write_text("")


def test_numbered_rotation_after_rotation_never_repeats_a_line(folder):
    store, source, logs, collector = folder
    for cycle in range(1, 6):
        with (logs / "app.log").open("a") as live:
            live.write(f"cycle {cycle} a\ncycle {cycle} b\n")
        drain(collector, source)
        rotate_numbered(logs)
        drain(collector, source)
    seen = counts(store)
    assert all(n == 1 for n in seen.values()), {m: n for m, n in seen.items() if n > 1}
    assert len(seen) == 10


def test_lines_written_to_the_live_file_after_a_rotation_are_read_once(folder):
    store, source, logs, collector = folder
    (logs / "app.log").write_text("one\n")
    drain(collector, source)
    rotate_numbered(logs)
    (logs / "app.log").write_text("two\n")
    drain(collector, source)
    rotate_numbered(logs)
    (logs / "app.log").write_text("three\n")
    drain(collector, source)
    assert counts(store) == Counter({"one": 1, "two": 1, "three": 1})


def test_a_renamed_archive_is_not_imported_again(folder):
    store, source, logs, collector = folder
    (logs / "app.log.2.gz").write_bytes(gzip.compress(b"archived\n"))
    drain(collector, source)
    os.rename(logs / "app.log.2.gz", logs / "app.log.3.gz")
    drain(collector, source)
    assert counts(store) == Counter({"archived": 1})


def test_a_file_that_replaces_another_at_the_same_name_is_read_from_its_start(folder):
    store, source, logs, collector = folder
    (logs / "app.log").write_text("old content\n")
    drain(collector, source)
    os.remove(logs / "app.log")
    (logs / "app.log").write_text("brand new\n")
    drain(collector, source)
    assert counts(store) == Counter({"old content": 1, "brand new": 1})


def test_a_deleted_single_file_is_handed_to_the_rotation_watch_and_then_let_go(tmp_path, monkeypatch):
    from logsentinel.portal import collect

    store = Store(tmp_path / "data")
    machine = store.put("machine", Machine(name="A").model_dump())
    path = tmp_path / "app.log"
    path.write_text("one\n")
    source = dict(
        Source(machine_id=machine, name="a", kind="file", path=str(path), enabled=True, history=True).model_dump(),
        id="s",
    )
    collector = Collector(store)
    try:
        assert collector.poll(source) == 1
        assert len(collector.handles) == 1
        os.unlink(path)
        collector.poll(source)
        assert not collector.handles, "the descriptor of a deleted file must not stay in the live table"
        assert len(collector.retired) == 1, "it drains through the rotation watch first"
        start = collect.time.monotonic()
        monkeypatch.setattr(collect.time, "monotonic", lambda: start + 400)
        collector.poll(source)
        assert not collector.retired, "and is closed once it has been quiet"
    finally:
        collector.close()
