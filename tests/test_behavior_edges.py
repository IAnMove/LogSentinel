"""Independent edge cases for the temporal-history contract."""
from datetime import datetime, timedelta, timezone
from logsentinel.config import Config
from logsentinel.core.engine import SentinelEngine
from test_behavior import login, weekdays, engine_for


def test_cold_start_never_claims_an_anomaly(tmp_path):
    evidence = engine_for(tmp_path).behavior.observe(login(datetime(2025, 2, 1, 3, tzinfo=timezone.utc)))
    assert evidence['status'] == 'insufficient_history'
    assert evidence['prior_events'] == 0
    assert evidence['anomalies'] == []


def test_replay_cannot_increase_history_count(tmp_path):
    profiler = engine_for(tmp_path).behavior
    for at in weekdays():
        profiler.observe(login(at))
        assert profiler.observe(login(at))['duplicate']
    result = profiler.observe(login(datetime(2025, 2, 1, 3, tzinfo=timezone.utc)))
    assert result['prior_events'] == 20


def test_profiles_isolate_host_user_and_ip(tmp_path):
    profiler = engine_for(tmp_path).behavior
    for at in weekdays():
        profiler.observe(login(at))
    at = datetime(2025, 2, 1, 3, tzinfo=timezone.utc)
    for overrides in [{'host': 'server2'}, {'user': 'bob'}, {'ip': '192.0.2.11'}]:
        result = profiler.observe(login(at, **overrides))
        assert result['prior_events'] == 0
        assert result['status'] == 'insufficient_history'


def test_out_of_order_event_never_uses_later_observations(tmp_path):
    profiler = engine_for(tmp_path).behavior
    for at in weekdays():
        profiler.observe(login(at))
    result = profiler.observe(login(datetime(2025, 1, 1, 3, tzinfo=timezone.utc)))
    assert result['prior_events'] == 0
    assert result['status'] == 'insufficient_history'


def test_ipv6_and_configured_timezone(tmp_path):
    cfg = Config(app={'data_dir': str(tmp_path)}, behavior={'timezone': 'Europe/Madrid'})
    profiler = SentinelEngine(cfg).behavior
    result = profiler.observe(login(datetime(2025, 1, 6, 23, tzinfo=timezone.utc), ip='2001:0db8::1'))
    assert result['local_hour'] == 0
    assert result['local_day_type'] == 'weekday'
    assert result['entity']['ip'] == '2001:db8::1'


def test_hour_distance_wraps_midnight(tmp_path):
    profiler = engine_for(tmp_path).behavior
    for at in weekdays():
        profiler.observe(login(at.replace(hour=23)))
    result = profiler.observe(login(datetime(2025, 2, 3, 0, tzinfo=timezone.utc)))
    assert result['status'] == 'observed_schedule'
    assert not result['anomalies']


def test_retention_is_bounded_and_expired_history_is_insufficient(tmp_path):
    import sqlite3
    profiler = engine_for(tmp_path).behavior
    start = datetime(2024, 1, 1, 9, tzinfo=timezone.utc)
    for i in range(100):
        profiler.observe(login(start + timedelta(days=i)))
    with sqlite3.connect(profiler.db_path) as conn:
        count = conn.execute('SELECT count(*) FROM behavior_events').fetchone()[0]
    assert count <= 91
    result = profiler.observe(login(datetime(2025, 1, 1, 9, tzinfo=timezone.utc)))
    assert result['prior_events'] == 0


def test_disabled_and_non_ssh_do_not_learn(tmp_path):
    cfg = Config(app={'data_dir': str(tmp_path)}, behavior={'enabled': False})
    entry = login(datetime(2025, 1, 6, 9, tzinfo=timezone.utc))
    assert SentinelEngine(cfg).behavior.observe(entry) is None
    entry.service = 'nginx'
    assert engine_for(tmp_path).behavior.observe(entry) is None
