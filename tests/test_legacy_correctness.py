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
