from datetime import datetime, timedelta, timezone
from logsentinel.core.models import LogEntry
from test_behavior import engine_for, login, weekdays


def trained(tmp_path):
    profiler = engine_for(tmp_path).behavior
    for at in weekdays():
        profiler.observe(login(at))
    return profiler


def test_backfill_cannot_normalize_previously_unusual_hour(tmp_path):
    profiler = trained(tmp_path)
    candidate = login(datetime(2025, 2, 3, 3, tzinfo=timezone.utc))
    assert 'unusual_hour' in profiler.observe(candidate)['anomalies']
    backfill = profiler.observe(login(datetime(2025, 1, 1, 3, tzinfo=timezone.utc)))
    assert not backfill['learned']
    assert 'unusual_hour' in profiler.observe(candidate)['anomalies']


def test_tolerated_hours_do_not_ratchet_baseline(tmp_path):
    profiler = trained(tmp_path)
    start = datetime(2025, 2, 3, 10, tzinfo=timezone.utc)
    for i in range(18):
        result = profiler.observe(login(start + timedelta(hours=i)))
    assert 'unusual_hour' in result['anomalies']


def test_omitted_timestamp_does_not_train(tmp_path):
    profiler = engine_for(tmp_path).behavior
    entry = LogEntry(service='sshd', hostname='h', message='Accepted publickey for alice from 192.0.2.10 port 50000 ssh2', raw='x')
    assert profiler.observe(entry) is None
