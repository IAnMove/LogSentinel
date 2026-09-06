"""Prove real SQLite handles are closed, including returns and errors."""

import sqlite3

import pytest

from logsentinel.core.models import Alert, AlertStatus, Incident, LLMVerdict, MemoryRule, MemoryRuleType
from logsentinel.memory.store import MemoryStore


@pytest.fixture
def connections(monkeypatch):
    opened = []
    original = sqlite3.connect
    def connect(*args, **kwargs):
        connection = original(*args, **kwargs)
        opened.append(connection)  # Prevent GC from concealing the handle leak.
        return connection
    monkeypatch.setattr(sqlite3, "connect", connect)
    yield opened
    for connection in opened:
        connection.close()


def assert_all_closed(connections):
    assert connections
    for connection in connections:
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connection.execute("SELECT 1")


def test_every_store_operation_closes_its_connection(tmp_path, connections):
    store = MemoryStore(tmp_path / "memory.db")
    rule = store.add_rule(MemoryRule(rule_type=MemoryRuleType.PATTERN, content="synthetic"))
    assert store.get_rule(rule.id) is not None
    assert store.get_rule("missing") is None
    assert store.list_rules()
    store.record_rule_hit(rule.id)
    assert store.set_rule_active(rule.id, False)
    store.record_feedback(None, "synthetic feedback", rule.id)
    alert = Alert(incident=Incident(service="synthetic", signature="synthetic"), verdict=LLMVerdict(title="Synthetic", summary="Synthetic"))
    store.save_alert(alert)
    assert store.get_alert(alert.id) is not None
    assert store.get_alert("missing") is None
    assert store.list_alerts()
    assert store.update_alert_status(alert.id, AlertStatus.DISMISSED)
    assert store.delete_rule(rule.id)
    store.clear_all_rules()
    assert_all_closed(connections)


def test_store_closes_connection_when_deserialization_raises(tmp_path, connections, monkeypatch):
    store = MemoryStore(tmp_path / "memory.db")
    rule = store.add_rule(MemoryRule(rule_type=MemoryRuleType.PATTERN, content="synthetic"))
    def fail(row):
        raise ValueError("synthetic corrupt row")
    monkeypatch.setattr(store, "_row_to_rule", fail)
    with pytest.raises(ValueError, match="synthetic corrupt row"):
        store.get_rule(rule.id)
    assert_all_closed(connections)
