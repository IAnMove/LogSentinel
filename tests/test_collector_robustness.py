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


def test_an_oversized_line_is_cut_and_does_not_hide_other_files(folder):
    store, source, logs = folder
    (logs / "big.log").write_text("x" * 260_000 + "\n")
    (logs / "ok.log").write_text("healthy line\n")
    Collector(store).poll(source)
    stored = messages(store)
    assert "healthy line" in stored
    (cut,) = [m for m in stored if m.startswith("xxx")]
    assert "line cut: about" in cut and len(cut.encode()) <= 256_000
    assert health(store)["status"] == "ok"


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


def freeze_now(monkeypatch, moment):
    from logsentinel.collectors import file_tailer

    class Clock(file_tailer.datetime):
        @classmethod
        def now(cls, tz=None):
            return moment if tz is None else moment.astimezone(tz)

    monkeypatch.setattr(file_tailer, "datetime", Clock)


def test_syslog_lines_without_a_year_are_never_dated_in_the_future(monkeypatch):
    from datetime import datetime, timezone

    from logsentinel.collectors.file_tailer import FileTailerCollector

    freeze_now(monkeypatch, datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc))
    parse = FileTailerCollector.parse_log_line
    assert parse("Feb 10 08:00:00 h sshd[1]: x").timestamp.isoformat().startswith("2026-02-10")
    assert parse("Sep 29 11:59:00 h sshd[1]: x").timestamp.isoformat().startswith("2026-09-29")
    assert parse("Dec 31 23:59:59 h sshd[1]: x").timestamp.isoformat().startswith("2025-12-31")
    # A day of clock skew is tolerated; a leap day resolves to a leap year.
    assert parse("Sep 30 09:00:00 h sshd[1]: x").timestamp.isoformat().startswith("2026-09-30")
    assert parse("Feb 29 08:00:00 h sshd[1]: x").timestamp.isoformat().startswith("2024-02-29")


def test_lines_without_a_zone_use_the_machine_timezone(folder):
    store, source, logs = folder
    machine = store.get("machine", source["machine_id"])
    store.put("machine", dict(machine, timezone="Europe/Madrid"), machine["id"])
    (logs / "app.log").write_text("2026-01-15 10:00:00 host app[1]: local time\n2026-01-15T10:00:00Z host app[1]: explicit utc\n")
    Collector(store).poll(source)
    stamps = {e["message"]: e["timestamp"] for e in store.events()}
    assert stamps["local time"].startswith("2026-01-15T09:00:00")
    assert stamps["explicit utc"].startswith("2026-01-15T10:00:00")


@pytest.mark.parametrize(
    "suffix, compress",
    [
        (".gz", gzip.compress),
        (".xz", __import__("lzma").compress),
        (".bz2", __import__("bz2").compress),
    ],
)
def test_a_truncated_archive_is_a_readable_error_not_a_crash(folder, suffix, compress):
    store, source, logs = folder
    archive = logs / ("cut.log" + suffix)
    archive.write_bytes(compress(b"a line of text\n" * 20000)[:-40])
    collector = Collector(store)
    assert collector.file(source, archive) == 0  # the first sight only records its stamp
    with pytest.raises(ValueError, match="truncated or corrupt"):
        for _ in range(40):  # each poll reads one batch; the cut is at the end
            collector.file(source, archive)


def xz_bytes(data, dictionary=None):
    import lzma

    if dictionary is None:
        return lzma.compress(data)
    return lzma.compress(data, format=lzma.FORMAT_XZ, filters=[{"id": lzma.FILTER_LZMA2, "dict_size": dictionary}])


def test_xz_reader_handles_seeks_padding_and_concatenated_streams():
    import io
    import lzma

    from logsentinel.portal.collect import open_xz

    first = b"".join(b"line %06d of the first stream\n" % i for i in range(20000))
    second = b"second stream line\n" * 500
    blob = xz_bytes(first) + b"\0\0\0\0" + xz_bytes(second)  # stream padding between streams
    # The standard library stops at padding between streams; xz itself reads on.
    expected = first + second
    assert lzma.LZMAFile(io.BytesIO(xz_bytes(first) + xz_bytes(second))).read() == expected
    reader = open_xz(io.BytesIO(blob))
    assert reader.read() == expected
    for target in (0, 12345, len(first) - 3, len(first) + 5, 7):  # forward, backward and across streams
        reader.seek(target)
        assert reader.tell() == target and reader.read(50) == expected[target : target + 50]
    reader.seek(0)
    assert reader.readline() == b"line 000000 of the first stream\n"


def test_an_xz_archive_that_demands_too_much_memory_is_refused(monkeypatch):
    import io
    import lzma

    from logsentinel.portal import collect

    monkeypatch.setattr(collect, "XZ_MEMORY_LIMIT", 8 * 1024 * 1024)
    hostile = xz_bytes(b"x" * 1000, dictionary=256 * 1024 * 1024)
    with pytest.raises(lzma.LZMAError, match="[Mm]emory"):
        collect.open_xz(io.BytesIO(hostile)).read()
    small = xz_bytes(b"ordinary\n", dictionary=1024 * 1024)  # the default preset itself wants 8 MiB
    assert collect.open_xz(io.BytesIO(small)).read() == b"ordinary\n"


def test_an_xz_source_over_the_limit_is_reported_as_a_bad_source(folder, monkeypatch):
    from logsentinel.portal import collect

    store, source, logs = folder
    monkeypatch.setattr(collect, "XZ_MEMORY_LIMIT", 8 * 1024 * 1024)
    archive = logs / "hostile.log.xz"
    archive.write_bytes(xz_bytes(b"line\n" * 100, dictionary=256 * 1024 * 1024))
    collector = Collector(store)
    assert collector.file(source, archive) == 0
    with pytest.raises(ValueError, match="needs more than 8 MiB of memory"):
        collector.file(source, archive)
