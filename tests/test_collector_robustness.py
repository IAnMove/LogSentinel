"""One bad file, a crowded folder or a deleted log must not blind the collector."""

import gzip
import json
import os
import time

import pytest

from logsentinel.portal import collect
from logsentinel.portal.collect import MAX_FOLDER_FILES, Collector
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store


@pytest.fixture
def folder(tmp_path):
    store = Store(tmp_path / "data")
    machine = store.put("machine", Machine(name="A").model_dump())
    logs = tmp_path / "logs"
    logs.mkdir()
    source = dict(
        Source(
            machine_id=machine, name="app", kind="folder", path=str(logs),
            pattern="*", enabled=True, history=True,
        ).model_dump(),
        id="s",
    )
    return store, source, logs


def messages(store):
    return sorted(e["message"] for e in store.events(limit=5000))


def health(store):
    return json.loads(store.meta("health:s"))


def test_an_unsupported_archive_does_not_stop_the_files_after_it(folder):
    store, source, logs = folder
    (logs / "a-first.zst").write_bytes(b"not readable")
    (logs / "b-second.log").write_text("second file line\n")
    (logs / "c-third.log").write_text("third file line\n")
    assert Collector(store).poll(source) == 2
    assert messages(store) == ["second file line", "third file line"]
    state = health(store)
    assert state["status"] == "error"
    assert "a-first.zst" in state["error"] and "1 of 3" in state["error"]


def test_an_oversized_line_is_reported_without_hiding_other_files(folder):
    store, source, logs = folder
    (logs / "big.log").write_text("x" * 260_000 + "\n")
    (logs / "ok.log").write_text("healthy line\n")
    Collector(store).poll(source)
    assert messages(store) == ["healthy line"]
    assert "big.log" in health(store)["error"]


def test_strict_polling_still_raises_for_the_read_check(folder):
    store, source, logs = folder
    (logs / "a.zst").write_bytes(b"x")
    with pytest.raises(ValueError, match="Unsupported archive"):
        Collector(store).poll(source, strict=True)


def test_a_crowded_folder_reads_the_newest_files_and_says_it_skipped_some(folder):
    store, source, logs = folder
    total = MAX_FOLDER_FILES + 5
    for i in range(total):
        path = logs / f"app-{i:03d}.log"
        path.write_text(f"line {i:03d}\n")
        os.utime(path, (1000 + i, 1000 + i))
    Collector(store).poll(source)
    read = messages(store)
    assert len(read) == MAX_FOLDER_FILES
    # The newest names sort last alphabetically, which the old slice dropped.
    assert f"line {total - 1:03d}" in read and "line 000" not in read
    assert "5 older matching files" in health(store)["error"]


def test_archives_are_skipped_without_history_and_imported_when_it_is_enabled(folder):
    store, source, logs = folder
    archive = logs / "auth.log.1.gz"
    archive.write_bytes(gzip.compress(b"old one\nold two\n"))
    quiet = dict(source, history=False, pattern="*.gz")
    collector = Collector(store)
    for _ in range(3):
        collector.poll(quiet)
    assert store.events() == []
    with store.connect() as db:
        writes = db.execute("SELECT count(*) FROM cursors").fetchone()[0]
    assert writes == 1
    loud = dict(source, history=True, pattern="*.gz")
    for _ in range(3):
        collector.poll(loud)
    assert messages(store) == ["old one", "old two"]


def test_a_deleted_log_stops_holding_its_descriptor_open(folder):
    store, source, logs = folder
    path = logs / "gone.log"
    path.write_text("before\n")
    collector = Collector(store)
    collector.poll(source)
    assert len(collector.handles) == 1
    path.unlink()
    (logs / "other.log").write_text("still here\n")
    collector.poll(source)
    assert collector.handles.keys() == {("s", str(logs / "other.log"))}
    assert len(collector.retired) == 1
    collector.retired[0]["quiet"] = time.monotonic() - 400
    collector.poll(source)
    assert collector.retired == []


def test_journal_capture_asks_for_long_fields(tmp_path, monkeypatch):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="A").model_dump())
    source = dict(
        Source(machine_id=machine, name="journal", kind="journald", enabled=True, history=True).model_dump(),
        id="j",
    )
    seen = []

    def fake(cmd, budget):
        seen.append(cmd)
        return b"", False

    monkeypatch.setattr(collect, "read_journal", fake)
    Collector(store).poll(source)
    assert "--all" in seen[0]


def test_journal_records_without_a_message_are_counted_not_lost_silently(tmp_path, monkeypatch):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="A").model_dump())
    source = dict(
        Source(machine_id=machine, name="journal", kind="journald", enabled=True, history=True).model_dump(),
        id="j",
    )
    lines = [
        json.dumps({"__CURSOR": "c1", "MESSAGE": None, "_SYSTEMD_UNIT": "big.service"}),
        json.dumps({"__CURSOR": "c2", "MESSAGE": "fine", "_SYSTEMD_UNIT": "ok.service"}),
    ]
    monkeypatch.setattr(collect, "read_journal", lambda cmd, budget: (("\n".join(lines) + "\n").encode(), False))
    Collector(store).poll(source)
    assert [e["message"] for e in store.events()] == ["fine"]
    with store.connect() as db:
        assert db.execute("SELECT value FROM metrics WHERE key='journal_skipped'").fetchone()[0] == 1
