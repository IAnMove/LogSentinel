"""A line too long to store is cut, and the source carries on after it."""

import gzip
import json

import pytest

from logsentinel.portal.collect import MAX_LINE, Collector
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store


@pytest.fixture
def file_source(tmp_path):
    store = Store(tmp_path / "data")
    machine = store.put("machine", Machine(name="A").model_dump())
    path = tmp_path / "app.log"
    source = dict(
        Source(machine_id=machine, name="app", kind="file", path=str(path), enabled=True, history=True).model_dump(),
        id="s",
    )
    return store, source, path


def stored(store):
    return [e["message"] for e in store.events(limit=100)]


def test_the_line_after_a_huge_one_is_read_and_nothing_is_read_twice(file_source):
    store, source, path = file_source
    path.write_text("before\n" + "y" * 3_000_000 + "\nafter\n")
    collector = Collector(store)
    # The giant line spends the whole batch, so the line after it comes next pass.
    assert collector.poll(source) + collector.poll(source) == 3
    assert collector.poll(source) == 0
    messages = stored(store)
    assert messages[0] == "before" and messages[2] == "after"
    assert messages[1].startswith("yyyy") and "more bytes were not stored" in messages[1]
    events = store.events(limit=100)
    assert 2_500_000 < events[1]["metadata"]["cut_bytes"] < 3_100_000


def test_a_cut_line_is_kept_within_the_limit_even_when_its_bytes_are_not_utf8(file_source):
    store, source, path = file_source
    path.write_bytes(b"\xff" * 300_000 + b"\nok\n")
    Collector(store).poll(source)
    first, second = stored(store)
    assert len(first.encode()) <= MAX_LINE and second == "ok"


def test_a_giant_line_still_being_written_waits_for_its_end(file_source):
    store, source, path = file_source
    path.write_bytes(b"z" * 400_000)
    collector = Collector(store)
    assert collector.poll(source) == 0
    assert collector.poll(source) == 0
    with path.open("ab") as handle:
        handle.write(b"z" * 10 + b"\nnext\n")
    assert collector.poll(source) == 2
    first, second = stored(store)
    assert first.startswith("zzz") and "line cut" in first and second == "next"


def test_the_start_of_a_cut_line_is_still_what_the_detectors_read(file_source):
    store, source, path = file_source
    path.write_text("Out of memory: Killed process 4242 (java)" + " pad" * 100_000 + "\n")
    Collector(store).poll(source)
    from logsentinel.portal.analysis import Analyzer
    from logsentinel.portal.signal_scan import scan_signals

    while scan_signals(Analyzer(store)):
        pass
    assert [json.loads(p["data"])["reasoning"] for p in store.rows("problems")] == ["oom"]


def test_a_compressed_file_with_a_huge_line_is_read_to_its_end(file_source):
    store, source, path = file_source
    folder = path.parent / "logs"
    folder.mkdir()
    (folder / "app.log.1.gz").write_bytes(gzip.compress(b"a" * 400_000 + b"\nlast\n"))
    source = dict(source, kind="folder", path=str(folder), pattern="*.gz")
    collector = Collector(store)
    assert sum(collector.poll(source) for _ in range(3)) == 2
    first, second = stored(store)
    assert "line cut" in first and second == "last"
