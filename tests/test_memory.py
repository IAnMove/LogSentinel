"""Unit tests for SQLite MemoryStore."""

from pathlib import Path
import tempfile
import pytest
from logsentinel.core.models import (
    Alert,
    AlertStatus,
    Category,
    Incident,
    LLMVerdict,
    LogEntry,
    MemoryRule,
    MemoryRuleType,
    Severity,
)
from logsentinel.memory.store import MemoryStore


@pytest.fixture
def temp_store():
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_memory.db"
        yield MemoryStore(db_path)


def test_rule_crud(temp_store):
    rule = MemoryRule(
        rule_type=MemoryRuleType.PATTERN,
        content="xkbcomp",
        description="Ignore xkbcomp",
    )
    temp_store.add_rule(rule)

    retrieved = temp_store.get_rule(rule.id)
    assert retrieved is not None
    assert retrieved.content == "xkbcomp"
    assert retrieved.hit_count == 0

    # Record hit
    temp_store.record_rule_hit(rule.id)
    updated = temp_store.get_rule(rule.id)
    assert updated.hit_count == 1
    assert updated.last_matched is not None

    # List rules
    rules = temp_store.list_rules()
    assert len(rules) == 1

    # Delete rule
    assert temp_store.delete_rule(rule.id)
    assert temp_store.get_rule(rule.id) is None


def test_alert_crud(temp_store):
    inc = Incident(service="sshd", signature="sshd:test", entries=[
        LogEntry(service="sshd", message="failed", raw="failed")
    ])
    verdict = LLMVerdict(
        alert_needed=True,
        severity=Severity.HIGH,
        category=Category.SECURITY,
        title="Test Alert",
        summary="Test Summary",
    )
    alert = Alert(incident=inc, verdict=verdict)

    temp_store.save_alert(alert)

    retrieved = temp_store.get_alert(alert.id)
    assert retrieved is not None
    assert retrieved.verdict.title == "Test Alert"
    assert retrieved.status == AlertStatus.NEW

    # Update status
    temp_store.update_alert_status(alert.id, AlertStatus.DISMISSED, feedback="User test reason")
    updated = temp_store.get_alert(alert.id)
    assert updated.status == AlertStatus.DISMISSED
    assert updated.user_feedback == "User test reason"
