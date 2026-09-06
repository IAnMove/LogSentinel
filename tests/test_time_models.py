from datetime import datetime, timezone, timedelta
import pytest
from logsentinel.core.models import LogEntry, Incident


def test_naive_event_time_is_normalized_to_explicit_utc():
    entry = LogEntry(message='x', raw='x', timestamp=datetime(2025, 1, 1))
    assert entry.timestamp.tzinfo is not None
    assert entry.timestamp.utcoffset() == timedelta(0)


def test_incident_bounds_follow_event_time_even_out_of_order():
    early = datetime(2025, 1, 1, tzinfo=timezone.utc)
    late = early + timedelta(hours=1)
    inc = Incident(service='ssh', signature='x')
    inc.add_entry(LogEntry(message='late', raw='late', timestamp=late))
    inc.add_entry(LogEntry(message='early', raw='early', timestamp=early))
    assert inc.first_seen == early
    assert inc.last_seen == late


def test_incident_prompt_renders_real_timezone():
    at = datetime(2025, 1, 1, 10, tzinfo=timezone(timedelta(hours=2)))
    inc = Incident(service='ssh', signature='x', first_seen=at, last_seen=at)
    assert '08:00:00 UTC' in inc.format_for_llm()
