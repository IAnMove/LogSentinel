"""Offline collector regressions using synthetic log content."""
from datetime import datetime, timezone

import pytest
from logsentinel.collectors.file_tailer import FileTailerCollector
from logsentinel.collectors.file_reader import FileReader


@pytest.mark.parametrize("stamp, expected, inferred", [
    ("2024-01-02T03:04:05+02:00", datetime(2024, 1, 2, 1, 4, 5, tzinfo=timezone.utc), False),
    ("2024-01-02T03:04:05.123456Z", datetime(2024, 1, 2, 3, 4, 5, 123456, tzinfo=timezone.utc), False),
    ("2024-01-02T03:04:05", datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc), True),
])
def test_file_timestamp_preserves_event_time(tmp_path, stamp, expected, inferred):
    path = tmp_path / "auth.log"
    path.write_text(f"{stamp} host sshd[123]: Accepted password for synthetic\n")
    entry, = FileReader.read_file(path)
    assert entry.timestamp == expected
    assert entry.service == "sshd"
    assert entry.pid == 123
    assert entry.hostname == "host"
    assert entry.message == "Accepted password for synthetic"
    assert entry.metadata.get("timestamp_inferred", False) is inferred


@pytest.mark.parametrize("line", ["Sep  5 12:34:56 host sshd[123]: message", "plain message", "not-a-date host sshd: message"])
def test_ambiguous_file_timestamp_is_marked(line):
    entry = FileTailerCollector.parse_log_line(line)
    assert entry.metadata.get("timestamp_inferred") is True
    if line.startswith("Sep"):
        assert entry.service == "sshd"
        assert entry.timestamp.month == 9
        assert entry.timestamp.day == 5
        assert entry.timestamp.hour == 12


@pytest.mark.asyncio
@pytest.mark.parametrize("rotation", [False, True])
async def test_tail_waits_for_complete_lines_and_drains_renamed_file(tmp_path, monkeypatch, rotation):
    import asyncio
    from logsentinel.config import FileSourceConfig
    path = tmp_path / "synthetic.log"
    path.write_bytes(b"old history\n")
    collector = FileTailerCollector(FileSourceConfig(paths=[str(path)]))
    tick = 0
    async def advance(_):
        nonlocal tick
        tick += 1
        if tick == 1:
            with path.open("ab") as f:
                f.write(b"new caf\xc3")
        elif tick == 2:
            with path.open("ab") as f:
                f.write(b"\xa9 complete\n")
            if rotation:
                path.rename(tmp_path / "synthetic.log.1")
                path.write_bytes(b"replacement\n")
        else:
            await collector.stop()
    monkeypatch.setattr(asyncio, "sleep", advance)
    entries = [entry async for entry in collector.stream()]
    assert [e.message for e in entries] == (["new café complete", "replacement"] if rotation else ["new café complete"])


@pytest.mark.asyncio
async def test_tail_resets_position_after_empty_truncation(tmp_path, monkeypatch):
    import asyncio
    from logsentinel.config import FileSourceConfig
    path = tmp_path / "synthetic.log"
    path.write_text("long old history\n")
    collector = FileTailerCollector(FileSourceConfig(paths=[str(path)]))
    tick = 0
    async def advance(_):
        nonlocal tick
        tick += 1
        if tick == 1:
            path.write_bytes(b"")
        elif tick == 2:
            path.write_bytes(b"new\n")
        else:
            await collector.stop()
    monkeypatch.setattr(asyncio, "sleep", advance)
    assert [e.message async for e in collector.stream()] == ["new"]
