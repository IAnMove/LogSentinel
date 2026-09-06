"""Journal subprocesses are always mocked; no live log access."""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from logsentinel.collectors.journald import JournaldCollector
from logsentinel.config import JournaldSourceConfig


@pytest.mark.parametrize("field,value", [
    ("MESSAGE", ["bad"]), ("MESSAGE", [999]), ("MESSAGE", None),
    ("MESSAGE", {}), ("SYSLOG_IDENTIFIER", []), ("SYSLOG_IDENTIFIER", {}),
    ("SYSLOG_IDENTIFIER", [1]), ("PRIORITY", []), ("PRIORITY", None),
    ("_PID", {}), ("_PID", None), ("_HOSTNAME", []),
])
def test_malformed_journal_fields_never_abort_collection(field, value):
    collector = JournaldCollector(JournaldSourceConfig())
    data = {"MESSAGE": "synthetic", field: value}
    entry = collector._parse_json_line(json.dumps(data))
    if field == "MESSAGE":
        assert entry is None
    else:
        assert entry is not None
        assert entry.message == "synthetic"


@pytest.mark.parametrize("stamp", [None, [], "bad", "9999999999999999999999999"])
def test_journal_inferred_timestamp_is_marked(stamp):
    entry = JournaldCollector(JournaldSourceConfig())._parse_json_line(json.dumps({
        "MESSAGE": "synthetic", "__REALTIME_TIMESTAMP": stamp}))
    assert entry.metadata.get("timestamp_inferred") is True


def test_journal_byte_message_and_real_timestamp():
    entry = JournaldCollector(JournaldSourceConfig())._parse_json_line(json.dumps({
        "MESSAGE": [111, 107], "__REALTIME_TIMESTAMP": "1704164645123456"}))
    assert entry.message == "ok"
    assert entry.timestamp == datetime(2024, 1, 2, 3, 4, 5, 123456, tzinfo=timezone.utc)
    assert entry.metadata.get("timestamp_inferred", False) is False


@pytest.mark.asyncio
@pytest.mark.parametrize("follow", [False, True])
async def test_journal_nonzero_exit_is_not_a_clean_empty_result(monkeypatch, follow):
    collector = JournaldCollector(JournaldSourceConfig())
    collector.journalctl_bin = "synthetic-journalctl"
    proc = SimpleNamespace(
        returncode=1,
        stdout=SimpleNamespace(readline=AsyncMock(return_value=b"")),
        communicate=AsyncMock(return_value=(b"", b"synthetic denied")),
        wait=AsyncMock(return_value=1), terminate=Mock(), kill=Mock(),
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    with pytest.raises(RuntimeError, match="journalctl.*1"):
        if follow:
            _ = [e async for e in collector.stream()]
        else:
            await collector.read_recent()


@pytest.mark.asyncio
async def test_missing_journal_binary_is_an_error_for_explicit_read():
    collector = JournaldCollector(JournaldSourceConfig())
    collector.journalctl_bin = None
    with pytest.raises(RuntimeError, match="journalctl"):
        await collector.read_recent()
