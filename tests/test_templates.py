"""Lines that differ only in the parts that change share a template."""

import time

import pytest

from logsentinel.portal.templates import MAX_KEY, template


@pytest.mark.parametrize(
    "a, b",
    [
        ("Accepted publickey for alice from 203.0.113.9 port 2222 ssh2", "Accepted publickey for alice from 198.51.100.4 port 55012 ssh2"),
        ("Started Session 42 of user ina.", "Started Session 9931 of user ina."),
        ("2026/10/07 10:00:01 [error] 12#0: *55 open() failed", "2026/10/07 11:30:59 [error] 7#0: *9 open() failed"),
        ('time="2026-10-07T10:00:00Z" level=info msg="x" container=a1b2c3d4e5f6', 'time="2026-10-08T09:12:33Z" level=info msg="x" container=0fe9d8c7b6a5'),
        ("Oct  7 10:00:00 host cron[1234]: (root) CMD (run)", "Oct 12 23:59:59 host cron[9]: (root) CMD (run)"),
        ("request 3f2a8b1c-1234-4abc-9def-0123456789ab took 12.5 ms", "request 9e8d7c6b-5555-4abc-9def-aaaaaaaaaaaa took 0.3 ms"),
        ("fe80::1 is unreachable", "2001:db8::dead:beef is unreachable"),
    ],
)
def test_changing_parts_are_masked(a, b):
    assert template("s", a) == template("s", b)


@pytest.mark.parametrize(
    "a, b",
    [
        ("Accepted publickey for alice", "Failed password for alice"),
        ("Out of memory: Killed process # (java)", "Out of memory: Killed process # (postgres)"),
        ("disk write failed", "disk write ok"),
    ],
)
def test_different_words_are_different_templates(a, b):
    assert template("s", a) != template("s", b)


def test_the_service_is_part_of_the_template():
    assert template("sshd", "session opened") != template("cron", "session opened")


def test_words_that_merely_contain_letters_a_to_f_are_not_hex():
    assert template("s", "deadbeef cafe faced") == ("s", "deadbeef cafe faced")
    assert template("s", "id deadbeef1 and cafe123") == ("s", "id <hex> and <hex>")


def test_keys_are_bounded_and_hostile_text_is_quick():
    long = "x" * 100_000
    started = time.perf_counter()
    key = template("s", long)
    hostile = template("s", "1.2.3.4" * 20_000) and template("s", "2026-01-01T00:00:00" * 5_000) and template("s", "a:" * 50_000)
    assert time.perf_counter() - started < 1.0
    assert len(key[1]) <= MAX_KEY and hostile
