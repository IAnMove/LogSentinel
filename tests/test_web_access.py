import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from logsentinel.portal.web_access import FIELD_LIMITS, MAX_LINE, parse_access_line

COMBINED = (
    '192.0.2.10 - - [10/Oct/2026:13:55:36 +0200] "GET /index.html?a=1 HTTP/1.1" 200 2326 '
    '"https://example.com/start" "Mozilla/5.0 (X11; Linux x86_64)"'
)


def test_a_combined_line_is_read_field_by_field():
    record = parse_access_line(COMBINED)
    assert record.ip == "192.0.2.10"
    assert record.method == "GET"
    assert record.target == "/index.html?a=1"
    assert record.protocol == "HTTP/1.1"
    assert record.status == 200 and record.size == 2326
    assert record.referer == "https://example.com/start"
    assert record.agent == "Mozilla/5.0 (X11; Linux x86_64)"
    assert record.forwarded_for == ""


def test_the_time_is_converted_to_utc_from_the_logged_offset():
    assert parse_access_line(COMBINED).time == datetime(2026, 10, 10, 11, 55, 36, tzinfo=timezone.utc)
    west = COMBINED.replace("+0200", "-0330")
    assert parse_access_line(west).time == datetime(2026, 10, 10, 17, 25, 36, tzinfo=timezone.utc)


def test_the_common_format_without_referer_and_agent_is_read():
    record = parse_access_line('192.0.2.11 - alice [01/Jan/2027:00:00:01 +0000] "POST /login HTTP/1.0" 302 -')
    assert (record.method, record.target, record.status, record.size) == ("POST", "/login", 302, None)
    assert record.referer == record.agent == ""


def test_escaped_quotes_in_the_agent_do_not_end_the_field():
    apache = COMBINED.replace("Mozilla/5.0 (X11; Linux x86_64)", r"evil\" \"injected")
    assert parse_access_line(apache).agent == r"evil\" \"injected"
    nginx = COMBINED.replace("Mozilla/5.0 (X11; Linux x86_64)", r"evil\x22 \x22injected")
    assert parse_access_line(nginx).agent == r"evil\x22 \x22injected"


def test_ipv6_is_accepted_and_a_mapped_ipv4_is_reported_as_ipv4():
    assert parse_access_line(COMBINED.replace("192.0.2.10", "2001:db8::1")).ip == "2001:db8::1"
    assert parse_access_line(COMBINED.replace("192.0.2.10", "::ffff:192.0.2.77")).ip == "192.0.2.77"


def test_a_trailing_request_time_and_a_forwarded_field_are_tolerated():
    assert parse_access_line(COMBINED + " 0.043").status == 200
    forwarded = parse_access_line(COMBINED + ' "198.51.100.4, 203.0.113.9"')
    assert forwarded.forwarded_for == "198.51.100.4, 203.0.113.9"
    assert forwarded.ip == "192.0.2.10"  # the peer, never the forgeable header


@pytest.mark.parametrize("request_line", ["-", r"\x16\x03\x01\x02\x00\x01", "GET", "get /lower HTTP/1.1"])
def test_a_request_line_that_is_not_a_request_keeps_its_text_without_a_method(request_line):
    record = parse_access_line(COMBINED.replace("GET /index.html?a=1 HTTP/1.1", request_line).replace(" 200 ", " 400 "))
    assert record.method == ""
    assert record.target == request_line
    assert record.status == 400


def test_a_request_without_a_protocol_is_an_http_0_9_request():
    record = parse_access_line(COMBINED.replace("GET /index.html?a=1 HTTP/1.1", "GET /old"))
    assert (record.method, record.target, record.protocol) == ("GET", "/old", "")


@pytest.mark.parametrize(
    "line",
    [
        "",
        "Oct 10 13:55:36 host sshd[1]: Failed password for root from 192.0.2.1 port 22 ssh2",
        "2026-10-10T13:55:36Z host app: GET /x 200",
        COMBINED.replace("192.0.2.10", "999.1.1.1"),
        COMBINED.replace("192.0.2.10", "example.com"),
        COMBINED.replace("Oct", "Okt"),
        COMBINED.replace("+0200", "+9999"),
        COMBINED.replace("+0200", "+0260"),
        COMBINED.replace("10/Oct", "31/Feb"),
        COMBINED.replace("13:55:36", "25:61:61"),
        COMBINED.replace(" 200 ", " 099 "),
        COMBINED.replace(" 200 ", " 600 "),
        COMBINED.replace(" 200 ", " 2OO "),
        COMBINED + "\nsecond line",
    ],
)
def test_lines_that_are_not_access_records_are_rejected(line):
    assert parse_access_line(line) is None


def test_a_trailing_newline_is_not_part_of_the_line():
    assert parse_access_line(COMBINED + "\r\n").status == 200


def test_hostile_lines_are_rejected_quickly():
    prefix = '192.0.2.10 - - [10/Oct/2026:13:55:36 +0000] "'
    hostile = [
        prefix + "a" * (MAX_LINE * 4),
        prefix + "\\" * 9000,
        prefix + 'GET /' + '\\"' * 4000 + " HTTP/1.1",
        prefix + 'GET / HTTP/1.1" 200 5 "' + "x" * 5000 + '" "' + "y" * 5000,
        "1" * 5000,
        "[" * 5000 + '"',
    ]
    started = time.perf_counter()
    for line in hostile:
        assert parse_access_line(line) is None
    assert time.perf_counter() - started < 1.0


def test_stored_fields_are_bounded_and_json_safe():
    long_target = "/" + "a" * 8000
    record = parse_access_line(COMBINED.replace("/index.html?a=1", long_target))
    stored = record.fields()
    assert len(stored["target"]) == FIELD_LIMITS["target"]
    assert len(parse_access_line(COMBINED.replace("Mozilla/5.0 (X11; Linux x86_64)", "u" * 2000)).fields()["agent"]) == FIELD_LIMITS["agent"]
    json.dumps(stored)
    assert set(stored) == {"ip", "method", "target", "protocol", "status", "size", "referer", "agent", "forwarded_for"}
    assert record.time - datetime(2026, 10, 10, tzinfo=timezone.utc) < timedelta(days=1)
