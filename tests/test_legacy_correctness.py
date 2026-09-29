"""Defects in the older pipeline that made it miss or mis-handle logs."""

import time

import pytest

from logsentinel.config import PrefilterConfig
from logsentinel.core.models import (
    Category, Incident, LogEntry, MemoryRule, MemoryRuleType,
)
from logsentinel.core.prefilter import PreFilter, compile_keyword
from logsentinel.llm.parser import ResponseParser
from logsentinel.memory.matcher import MemoryMatcher
from logsentinel.memory.store import MemoryStore


def entry(message, **kwargs):
    return LogEntry(service=kwargs.pop("service", "kernel"), message=message, raw=message, **kwargs)


def test_shipped_audit_keyword_matches_a_real_denial():
    prefilter = PreFilter(PrefilterConfig())
    line = 'audit: type=1400 audit(1): apparmor="DENIED" operation="open" profile="x" denied_mask="r"'
    ok, category = prefilter.should_analyze(entry("audit: op=open access denied for pid 4"))
    assert (ok, category) == (True, Category.SECURITY)
    # The literal keyword text is still what plain keywords are: no accidental regex.
    assert compile_keyword("sudo:").search("sudo: pam failure")
    assert not compile_keyword("i/o error").search("i0o error")
    assert compile_keyword("chronyd[").search("chronyd[123]: ok")
    assert PreFilter(PrefilterConfig()).should_analyze(entry(line))[0]


def test_an_invalid_pattern_keyword_falls_back_to_literal_text():
    assert compile_keyword("broken(.*").search("a broken(.* keyword")


def test_error_priority_still_reaches_analysis_without_keywords():
    ok, category = PreFilter(PrefilterConfig()).should_analyze(entry("nothing special", priority=3))
    assert (ok, category) == (True, Category.SYSTEM_ERROR)


def test_pattern_rules_cannot_hang_the_engine(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.add_rule(MemoryRule(rule_type=MemoryRuleType.PATTERN, content="(a+)+$"))
    incident = Incident(service="x", signature="s", entries=[entry("a" * 60 + "!")])
    started = time.perf_counter()
    suppressed, rule = MemoryMatcher(store).evaluate_fast_suppression(incident)
    assert (suppressed, rule) == (False, None)
    assert time.perf_counter() - started < 2


def test_pattern_rules_still_suppress_matching_incidents(tmp_path):
    store = MemoryStore(tmp_path / "memory.db")
    store.add_rule(MemoryRule(rule_type=MemoryRuleType.PATTERN, content=r"cron\[\d+\]: .* finished"))
    incident = Incident(service="cron", signature="s", entries=[entry("cron[12]: job finished")])
    assert MemoryMatcher(store).evaluate_fast_suppression(incident)[0]


def test_ip_matching_has_a_public_name_and_keeps_the_old_one():
    assert MemoryMatcher.matches_ip("from 10.1.2.3 port 22", "10.1.0.0/16")
    assert MemoryMatcher._matches_ip("from 10.1.2.3 port 22", "10.1.0.0/16")
    assert not MemoryMatcher.matches_ip("from 10.2.2.3 port 22", "10.1.0.0/16")


@pytest.mark.parametrize(
    "reply, expected",
    [
        ('{"a": 1}', '{"a": 1}'),
        ('<think>hmm</think>\n{"a": 1}', '{"a": 1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('```{"a": 1}```', '{"a": 1}'),
        ('<think>x</think>```json\n{"a": 1}\n```', '{"a": 1}'),
        ('Sure! {"a": 1}', 'Sure! {"a": 1}'),
        ('text ```json\n{"a": 1}\n``` more', 'text ```json\n{"a": 1}\n``` more'),
    ],
)
def test_both_pipelines_unwrap_replies_the_same_way(reply, expected):
    assert ResponseParser.unwrap(reply) == expected


def test_legacy_files_that_hold_logs_and_secrets_are_owner_only(tmp_path):
    import asyncio
    import stat

    from logsentinel.config import Config, FileNotifierConfig
    from logsentinel.notifiers.file import FileNotifier

    store = MemoryStore(tmp_path / "state" / "memory.db")
    store.add_rule(MemoryRule(rule_type=MemoryRuleType.SERVICE, content="cron"))
    assert stat.S_IMODE(store.db_path.stat().st_mode) == 0o600
    with store._get_connection() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

    settings = tmp_path / "config.yaml"
    settings.write_text("old")
    settings.chmod(0o644)
    Config().save(settings)
    assert stat.S_IMODE(settings.stat().st_mode) == 0o600

    alerts = tmp_path / "alerts.jsonl"
    alerts.write_text("")
    alerts.chmod(0o644)
    notifier = FileNotifier(FileNotifierConfig(enabled=True, path=str(alerts)), alerts)
    assert asyncio.run(notifier.test())
    assert stat.S_IMODE(alerts.stat().st_mode) == 0o600


def test_old_alerts_expire_and_recent_ones_stay(tmp_path):
    from datetime import datetime, timedelta, timezone

    from logsentinel.core.models import Alert, LLMVerdict

    store = MemoryStore(tmp_path / "memory.db")
    old = Alert(incident=Incident(service="x", signature="s"), verdict=LLMVerdict(title="old", summary="s"),
                created_at=datetime.now(timezone.utc) - timedelta(days=200))
    new = Alert(incident=Incident(service="x", signature="s"), verdict=LLMVerdict(title="new", summary="s"))
    store.save_alert(old)
    store.save_alert(new)
    assert store.prune_alerts(90) == 1
    assert [a.verdict.title for a in store.list_alerts()] == ["new"]


@pytest.mark.asyncio
async def test_tail_keeps_the_head_of_a_runaway_line_and_moves_on(tmp_path, monkeypatch):
    import asyncio

    from logsentinel.collectors.file_tailer import MAX_LINE_BYTES, FileTailerCollector
    from logsentinel.config import FileSourceConfig

    path = tmp_path / "synthetic.log"
    path.write_text("history\n")
    collector = FileTailerCollector(FileSourceConfig(paths=[str(path)]))
    tick = 0

    async def advance(_):
        nonlocal tick
        tick += 1
        if tick == 1:
            with path.open("ab") as f:
                f.write(b"H" * (MAX_LINE_BYTES * 3) + b"\nnext line\n")
        else:
            await collector.stop()

    monkeypatch.setattr(asyncio, "sleep", advance)
    messages = [e.message async for e in collector.stream()]
    assert len(messages) == 2
    assert len(messages[0]) <= MAX_LINE_BYTES and messages[0].startswith("HHH")
    assert messages[1] == "next line"
