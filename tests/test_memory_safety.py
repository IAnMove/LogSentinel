"""Offline regression tests for conservative suppression and feedback."""

import pytest

from logsentinel.core.models import Alert, Incident, LLMVerdict, LogEntry, MemoryRule, MemoryRuleType
from logsentinel.memory.feedback import FeedbackLearner
from logsentinel.memory.matcher import MemoryMatcher
from logsentinel.memory.store import MemoryStore


def incident(*messages, service="sshd"):
    return Incident(service=service, signature="sshd:normalized <IP>", count=len(messages), entries=[
        LogEntry(service=service, message=message, raw=message) for message in messages
    ])


@pytest.fixture
def store(tmp_path):
    return MemoryStore(tmp_path / "memory.db")


@pytest.mark.parametrize("rule_type,content,allowed,unrelated", [
    (MemoryRuleType.PATTERN, "routine", "routine health check", "privilege escalation"),
    (MemoryRuleType.IP_ADDRESS, "192.0.2.1", "routine from 192.0.2.1", "failure from 198.51.100.2"),
])
def test_rule_must_cover_every_entry_before_suppressing_batch(store, rule_type, content, allowed, unrelated):
    rule = store.add_rule(MemoryRule(rule_type=rule_type, content=content))
    matcher = MemoryMatcher(store)
    assert matcher.evaluate_fast_suppression(incident(allowed, unrelated)) == (False, None)
    assert store.get_rule(rule.id).hit_count == 0
    assert matcher.evaluate_fast_suppression(incident(allowed, allowed))[0] is True
    assert store.get_rule(rule.id).hit_count == 1
    assert matcher.evaluate_fast_suppression(incident()) == (False, None)


@pytest.mark.parametrize("target,text,expected", [
    ("999.1.2.3", "from 999.1.2.3", False),
    ("192.0.2.0/99", "from 192.0.2.0/99", False),
    ("", "failure", False),
    ("routine", "routine", False),
    ("192.0.2.1", "from 192.0.2.10", False),
    ("192.0.2.0/24", "from 192.0.2.12", True),
    ("2001:db8::1", "from [2001:0db8:0:0:0:0:0:1]:443", True),
    ("2001:db8::/32", "from 2001:db8::2", True),
])
def test_ip_matching_validates_addresses(target, text, expected):
    assert MemoryMatcher._matches_ip(text, target) is expected


@pytest.mark.parametrize("content", ["", "[broken"])
def test_invalid_patterns_cannot_suppress(store, content):
    store.add_rule(MemoryRule(rule_type=MemoryRuleType.PATTERN, content=content))
    assert MemoryMatcher(store).evaluate_fast_suppression(incident(content + " failure")) == (False, None)


@pytest.mark.parametrize("suggested", [".*", "(a+)+$", None])
def test_dismiss_always_uses_literal_observed_messages_scoped_to_service(store, suggested):
    original = incident("routine [check] from 192.0.2.1", "routine (done)")
    alert = Alert(incident=original, verdict=LLMVerdict(title="Synthetic", summary="Synthetic", suggested_ignore_pattern=suggested))
    rule = FeedbackLearner(store).learn_from_alert_dismiss(alert)
    assert rule is not None
    matcher = MemoryMatcher(store)
    assert matcher.evaluate_fast_suppression(original)[0] is True
    assert matcher.evaluate_fast_suppression(incident("unrelated failure")) == (False, None)
    assert matcher.evaluate_fast_suppression(incident("routine (done) and compromised")) == (False, None)
    assert matcher.evaluate_fast_suppression(incident("routine (done)", service="other")) == (False, None)


def test_dismiss_empty_incident_creates_no_rule(store):
    alert = Alert(incident=incident(), verdict=LLMVerdict(title="Synthetic", summary="Synthetic"))
    assert FeedbackLearner(store).learn_from_alert_dismiss(alert) is None
    assert store.list_rules() == []


@pytest.mark.parametrize("text", ["no ignores 192.0.2.1", "never ignore 192.0.2.1", "investigate 192.0.2.1", "service:sshd except failures", "999.1.2.3", "192.0.2.0/99"])
def test_natural_language_is_not_reinterpreted_as_fast_suppression(store, text):
    rule = FeedbackLearner(store).learn_from_text(text)
    assert rule.rule_type == MemoryRuleType.SEMANTIC
    assert rule.content == text
    assert MemoryMatcher(store).evaluate_fast_suppression(incident("failure from 192.0.2.1")) == (False, None)


@pytest.mark.parametrize("text,expected", [("192.0.2.1", "192.0.2.1"), ("ignore 192.0.2.0/24", "192.0.2.0/24"), ("2001:db8::1", "2001:db8::1")])
def test_unambiguous_ip_inference(store, text, expected):
    rule = FeedbackLearner(store).learn_from_text(text)
    assert rule.rule_type == MemoryRuleType.IP_ADDRESS
    assert rule.content == expected


@pytest.mark.parametrize("text,rule_type", [("", None), ("192.0.2.0/99", MemoryRuleType.IP_ADDRESS), ("[", MemoryRuleType.PATTERN)])
def test_invalid_explicit_rules_are_rejected_before_persistence(store, text, rule_type):
    with pytest.raises(ValueError):
        FeedbackLearner(store).learn_from_text(text, rule_type=rule_type)
    assert store.list_rules() == []

