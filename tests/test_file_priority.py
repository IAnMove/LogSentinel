"""File lines that clearly state a failure get a syslog priority, so the urgent lane works for files."""

import pytest

from logsentinel.portal.collect import derive_priority, normalize
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store


@pytest.mark.parametrize(
    "service, message, expected",
    [
        ("kernel", "Out of memory: Killed process 4242 (java)", 2),
        ("kernel", "[12.3] kernel panic - not syncing: VFS", 2),
        ("kernel", "app[123]: segfault at 0 ip 00007f rip", 2),
        ("app", "2026-10-07 10:00:00 [CRITICAL] database unreachable", 2),
        ("app", "FATAL: password authentication failed", 2),
        ("app", "ERROR: disk write failed", 3),
        ("nginx", "2026/10/07 10:00:00 [error] 12#0: open() failed", 3),
        ("app", "level=error msg=\"boom\"", 3),
        ("app", "INFO request served in 12 ms", None),
        ("app", "user reported an error in the form", None),
        ("app", "errors=0 warnings=0", None),
        ("kernel", "eth0: link up", None),
        ("app", "the critical path took 2 ms", None),
    ],
)
def test_clear_failure_statements_get_a_priority_and_ordinary_text_does_not(service, message, expected):
    assert derive_priority(message, service) == expected


def test_a_file_oom_line_becomes_urgent_at_ingest(tmp_path):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="A").model_dump())
    source = store.get("source", store.put("source", Source(name="f", machine_id=machine, kind="push", enabled=True).model_dump()))
    store.ingest(source, [
        normalize("Oct  7 10:00:00 host kernel: Out of memory: Killed process 4242 (java)", "/var/log/kern.log", "a"),
        normalize("Oct  7 10:00:01 host cron[1]: (root) CMD (run-parts)", "/var/log/syslog", "b"),
    ])
    with store.connect() as db:
        urgent = dict(db.execute("SELECT origin, urgent FROM events").fetchall())
    assert urgent == {"a": 1, "b": 0}


def test_a_line_that_already_carries_a_priority_keeps_it():
    event = normalize("2026-10-07T10:00:00Z host app: ERROR something", "/var/log/app.log", "x")
    assert event["priority"] == 3
    event["priority"] = 6  # what a journal record would say wins over the words
    assert event["priority"] == 6
