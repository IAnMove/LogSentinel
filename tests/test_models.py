"""Unit tests for LogSentinel data models."""

from datetime import datetime, timezone
import pytest
from logsentinel.core.models import (
    Alert,
    AlertStatus,
    Category,
    Incident,
    LLMVerdict,
    LogEntry,
    LogSourceType,
    MemoryRule,
    MemoryRuleType,
    Severity,
)


def test_severity_ranks():
    assert Severity.CRITICAL.rank > Severity.HIGH.rank
    assert Severity.HIGH.rank > Severity.MEDIUM.rank
    assert Severity.MEDIUM.rank > Severity.LOW.rank
    assert Severity.LOW.rank > Severity.INFO.rank

    assert Severity.CRITICAL.is_at_least(Severity.HIGH)
    assert Severity.HIGH.is_at_least("MEDIUM")
    assert not Severity.LOW.is_at_least(Severity.HIGH)


def test_log_entry_creation():
    entry = LogEntry(
        service="sshd",
        message="Failed password for root from 1.2.3.4",
        raw="raw log line",
        priority=3,
        hostname="server1",
    )
    assert entry.service == "sshd"
    assert entry.source_type == LogSourceType.JOURNALD
    assert "Failed password" in entry.get_summary_line()


def test_incident_aggregation():
    inc = Incident(service="sshd", signature="sshd:test", category_hint=Category.SECURITY)
    e1 = LogEntry(service="sshd", message="failed 1", raw="raw 1", hostname="srv")
    e2 = LogEntry(service="sshd", message="failed 2", raw="raw 2")

    inc.add_entry(e1)
    inc.add_entry(e2)

    assert inc.count == 2
    assert inc.hostname == "srv"
    formatted = inc.format_for_llm()
    assert "Event Count: 2" in formatted
    assert "failed 1" in formatted


def test_llm_verdict_and_alert():
    verdict = LLMVerdict(
        alert_needed=True,
        severity=Severity.HIGH,
        category=Category.SECURITY,
        title="SSH Brute Force",
        summary="Attacker tried multiple passwords",
        recommended_action="Block IP",
    )
    inc = Incident(service="sshd", signature="sshd:test")
    alert = Alert(incident=inc, verdict=verdict)

    assert alert.id.startswith("alt-")
    assert alert.status == AlertStatus.NEW
    assert alert.verdict.severity == Severity.HIGH
