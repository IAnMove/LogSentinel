"""Engine contracts, exercised without collectors/network or user state."""
import asyncio
from unittest.mock import AsyncMock

from logsentinel.config import Config
from logsentinel.core.engine import SentinelEngine
from logsentinel.core.models import Incident, LogEntry, LLMVerdict, MemoryRule, MemoryRuleType, Category, AlertStatus


def make_engine(tmp_path, **kwargs):
    engine = SentinelEngine(Config(app={'data_dir': str(tmp_path)}, notifiers={'desktop': {'enabled': False}, 'file': {'enabled': False}}, **kwargs))
    engine.llm_client.analyze = AsyncMock(return_value=LLMVerdict(title='Needs review', summary='Evidence'))
    return engine


def incident(category=Category.SECURITY):
    return Incident(service='sshd', signature='x', category_hint=category, entries=[LogEntry(service='sshd', message='Failed password', raw='Failed password')])


def test_memory_disabled_really_disables_suppression(tmp_path):
    engine = make_engine(tmp_path, memory={'enabled': False})
    engine.memory_store.add_rule(MemoryRule(rule_type=MemoryRuleType.SERVICE, content='sshd'))
    result = asyncio.run(engine.process_incident(incident()))
    assert result.verdict.alert_needed
    engine.llm_client.analyze.assert_awaited_once()
    assert not engine.llm_client.analyze.call_args.kwargs.get('memory_context')


def test_no_delivery_does_not_claim_notified(tmp_path):
    engine = make_engine(tmp_path)
    result = asyncio.run(engine.process_incident(incident()))
    assert result.channels_notified == []
    assert result.status == AlertStatus.NEW
    assert engine.memory_store.get_alert(result.id).status == AlertStatus.NEW


def test_alert_is_durable_before_notification_cancellation(tmp_path):
    engine = make_engine(tmp_path)
    attempted = []

    async def cancelled(alert):
        attempted.append(alert.id)
        raise asyncio.CancelledError()

    engine.dispatcher.dispatch = cancelled
    import pytest
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(engine.process_incident(incident()))
    assert engine.memory_store.get_alert(attempted[0]) is not None


def test_collector_failure_is_observable_and_stop_joins_tasks(tmp_path):
    engine = make_engine(tmp_path, sources={'journald': {'enabled': False}, 'files': {'enabled': True}})

    async def broken_stream():
        raise RuntimeError('synthetic collector failure')
        yield

    engine.file_collector.stream = broken_stream
    async def run():
        await engine.start()
        await asyncio.sleep(0)
        assert hasattr(engine, 'raise_if_failed'), 'No source failure supervision'
        import pytest
        with pytest.raises(RuntimeError, match='synthetic collector failure'):
            engine.raise_if_failed()
        await engine.stop()
        assert all(task.done() for task in engine._collector_tasks)
    asyncio.run(run())


def test_invented_memory_rule_cannot_authorize_suppression(tmp_path):
    engine = make_engine(tmp_path)
    engine.llm_client.analyze.return_value = LLMVerdict(title='Suppressed', summary='claimed preference', alert_needed=False, matched_memory_rule='mem-nonexistent')
    result = asyncio.run(engine.process_incident(incident()))
    assert result.verdict.alert_needed
    assert result.status != AlertStatus.AUTO_SUPPRESSED


def test_anomaly_is_not_hidden_by_broad_service_rule(tmp_path):
    engine = make_engine(tmp_path)
    engine.memory_store.add_rule(MemoryRule(rule_type=MemoryRuleType.SERVICE, content='sshd'))
    result = asyncio.run(engine.process_incident(incident(Category.ANOMALY)))
    assert result.verdict.alert_needed
    engine.llm_client.analyze.assert_awaited_once()
