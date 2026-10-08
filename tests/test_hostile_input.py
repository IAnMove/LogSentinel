"""Text a stranger can put in a log must never cost more than a moment to process."""

import time

import pytest

from logsentinel.portal.analysis import grouping_key
from logsentinel.portal.compaction import representation
from logsentinel.portal.injection import looks_like_instruction
from logsentinel.portal.rules import redact as portal_redact
from logsentinel.portal.ssh_notifications import rejection_form
from logsentinel.redact import redact

SIZE = 8_000

HOSTILE = {
    "pairs of digits": "Out of memory: killed" + " 1" * (SIZE // 2) + "x",
    "digits and spaces": " 12" * (SIZE // 3) + "x",
    "spaces then text": " " * SIZE + "x",
    "dotted numbers": "1." * (SIZE // 2),
    "pid markers": "[1]" * (SIZE // 3) + "pid " * 100,
    "key equals": "password=" * (SIZE // 9),
    "bearer": "Bearer " * (SIZE // 7),
    "open pem": "-----BEGIN PRIVATE KEY-----" + "A" * SIZE,
    "quotes": '"' * SIZE,
    "braces": "{" * SIZE,
    "unicode spaces": "  " * (SIZE // 2) + "x",
    "ssh shaped": "Failed password for invalid user " + "a" * SIZE + " from 1.2.3.4 port 22 ssh2",
    "ignore shaped": "ignore " * (SIZE // 7) + "previous instructions",
    "scheduler shaped": 'Running job "' + 'a" (scheduled at ' * (256_000 // 20) + "x",
}


def event(message):
    return {"message": message, "service": "app", "source_id": "s", "metadata": {}, "id": "e", "priority": None}


def unit_event(message):
    """A journald line from a unit, which is what compaction's known formats look at."""
    stamp = "2026-10-05T10:00:00Z INFO apscheduler.executors.default: "
    return {"message": stamp + message, "service": "app", "source_id": "s", "metadata": {"systemd_unit": "app.service"}, "id": "e", "priority": 6}


FUNCTIONS = {
    "grouping_key": lambda text: grouping_key(event(text)),
    "representation": lambda text: representation(event(text)),
    "representation (unit)": lambda text: representation(unit_event(text)),
    "rejection_form": lambda text: rejection_form(dict(event(text), service="sshd")),
    "looks_like_instruction": looks_like_instruction,
    "redact": redact,
    "portal redact": portal_redact,
}


@pytest.mark.parametrize("function", FUNCTIONS)
@pytest.mark.parametrize("name", HOSTILE)
def test_hostile_text_is_processed_quickly(function, name):
    started = time.perf_counter()
    FUNCTIONS[function](HOSTILE[name])
    assert time.perf_counter() - started < 1.0, f"{function} took too long on {name!r}"


@pytest.mark.parametrize(
    "message, expected",
    [
        ("worker 3 took 12 34", "worker 3 took"),
        ("retry 7", "retry"),
        ("12", "12"),
        ("12 34", "12"),
        ("  12", ""),
        ("pid 99 exited 4", "pid=# exited"),
        ("from 10.0.0.1 port 22 55", "from #ip port"),
        ("done\t5 \n6  ", "done"),
        ("version 2x", "version 2x"),
    ],
)
def test_trailing_counters_do_not_change_what_a_line_groups_with(message, expected):
    assert grouping_key(event(message))[2] == expected
