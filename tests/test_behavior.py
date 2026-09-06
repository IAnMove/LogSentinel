"""Temporal baselines use observed prior events, never invented schedules."""
from datetime import datetime, timedelta, timezone

from logsentinel.config import Config
from logsentinel.core.engine import SentinelEngine
from logsentinel.core.models import LogEntry


def login(at, ip="192.0.2.10", user="alice", host="server1"):
    message = f"Accepted publickey for {user} from {ip} port 50000 ssh2"
    return LogEntry(timestamp=at, service="sshd", hostname=host, message=message, raw=message, priority=6)


def engine_for(tmp_path):
    cfg = Config(behavior={'enabled': True}, app={"data_dir": str(tmp_path)}, notifiers={"desktop": {"enabled": False}, "file": {"enabled": False}})
    return SentinelEngine(cfg)


def weekdays():
    start = datetime(2025, 1, 6, 9, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(26) if (start + timedelta(days=i)).weekday() < 5]


def test_weekend_access_uses_persistent_prior_weekday_history(tmp_path):
    engine = engine_for(tmp_path)
    assert hasattr(engine, "behavior"), "Engine lacks a persistent behavior profiler"
    for at in weekdays():
        evidence = engine.behavior.observe(login(at))
        assert not evidence["anomalies"]
    restarted = engine_for(tmp_path)
    at = datetime(2025, 2, 1, 3, tzinfo=timezone.utc)
    evidence = restarted.behavior.observe(login(at))
    assert evidence["prior_events"] == 20
    assert evidence["status"] == "unusual"
    assert set(evidence["anomalies"]) == {"unseen_day_type", "unusual_hour"}
    assert evidence["prior_day_type_counts"] == {"weekday": 20, "weekend": 0}
    assert evidence["prior_hours"] == [9]
    assert evidence["event_time"] == at.isoformat()
    assert evidence["timezone"] == "UTC"
    assert evidence["learned"] is False  # quarantine unusual activity, not automatic trust


def test_ingestion_learns_normal_access_and_sends_evidence_to_llm(tmp_path):
    import asyncio
    from logsentinel.core.models import LLMVerdict
    from logsentinel.llm.prompts import build_analysis_prompt
    engine = engine_for(tmp_path)
    received = []

    async def analyze(incident, memory_context=None):
        received.append(incident)
        return LLMVerdict(title="Review unusual login", summary="Check maintenance schedule")

    engine.llm_client.analyze = analyze

    async def run():
        for at in weekdays():
            await engine.ingest_log(login(at))
        await engine.aggregator.flush_all()
        assert not received  # learn normality without one LLM call per normal login
        await engine.ingest_log(login(datetime(2025, 2, 1, 3, tzinfo=timezone.utc)))
        await engine.aggregator.flush_all()
    asyncio.run(run())
    assert len(received) == 1, "An unusual successful SSH login never reached analysis"
    prompt = build_analysis_prompt(received[0])
    assert 'unseen_day_type' in prompt
    assert 'prior_events' in prompt
    saved = engine.memory_store.list_alerts()
    assert len(saved) == 1
    assert saved[0].incident.entries[0].metadata['behavior']['prior_events'] == 20


def test_unparsed_timestamps_do_not_train_a_schedule(tmp_path):
    engine = engine_for(tmp_path)
    entry = login(datetime(2025, 1, 6, 9, tzinfo=timezone.utc))
    entry.metadata['timestamp_inferred'] = True
    assert engine.behavior.observe(entry) is None


def test_future_events_cannot_poison_baseline_retention(tmp_path):
    engine = engine_for(tmp_path)
    future = datetime.now(timezone.utc) + timedelta(days=365)
    assert engine.behavior.observe(login(future)) is None
