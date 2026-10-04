"""Deterministic findings about web traffic."""

import json
import time
from datetime import datetime, timezone

import pytest

from logsentinel.portal.analysis import Analyzer
from logsentinel.portal.collect import normalize
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.signal_scan import scan_signals
from logsentinel.portal.store import Store

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def line(ip="192.0.2.1", status=200, target="/", when=None, method="GET", agent="Mozilla/5.0"):
    when = datetime.fromtimestamp(time.time() - 120 if when is None else when, timezone.utc)
    stamp = f"{when.day:02d}/{MONTHS[when.month - 1]}/{when.year}:{when:%H:%M:%S} +0000"
    return f'{ip} - - [{stamp}] "{method} {target} HTTP/1.1" {status} 512 "-" "{agent}"'


@pytest.fixture
def site(tmp_path):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="Web host").model_dump())
    sid = store.put("source", Source(name="nginx", machine_id=machine, kind="push", enabled=True).model_dump())
    return store, store.get("source", sid)


def send(store, source, lines, tag="a"):
    store.ingest(source, [normalize(text, "remote", f"{tag}{i}") for i, text in enumerate(lines)])


def problems(store):
    return [dict(row, data=json.loads(row["data"])) for row in store.rows("problems")]


def run(store):
    return scan_signals(Analyzer(store))


def burst(count, *, status=502, spread=1, start=None, **kwargs):
    base = time.time() - 600 if start is None else start
    return [line(status=status, when=base + n * spread, **kwargs) for n in range(count)]


def test_a_burst_of_server_errors_is_one_high_finding_with_a_digest(site):
    store, source = site
    lines = burst(7, target="/api/orders?token=hunter2") + burst(5, status=500, target="/api/users", ip="198.51.100.7")
    send(store, source, lines + [line() for _ in range(50)])
    run(store)
    (found,) = problems(store)
    assert found["severity"] == "HIGH" and found["data"]["category"] == "reliability"
    assert found["data"]["reasoning"] == "web_server_errors"
    summary = found["data"]["summary"]
    assert "12 requests from 2 clients" in summary
    assert "502 (7)" in summary and "500 (5)" in summary
    assert "/api/orders (7)" in summary and "/api/users (5)" in summary
    assert "192.0.2.1 (7)" in summary and "198.51.100.7 (5)" in summary
    assert "token" not in summary and "hunter2" not in summary
    assert "Deterministic signal" in summary


def test_the_digest_follows_the_portal_language(site):
    store, source = site
    settings = store.settings().model_copy(update={"language": "es"})
    store.set_meta("settings", settings.model_dump_json())
    send(store, source, burst(10))
    run(store)
    assert "10 peticiones de 1 clientes" in problems(store)[0]["data"]["summary"]


def test_fewer_errors_than_the_threshold_or_spread_too_thin_are_not_a_finding(site):
    store, source = site
    send(store, source, burst(9), "few")
    # One error every two minutes for an hour, well before the others.
    send(store, source, burst(30, spread=120, start=time.time() - 7200), "thin")
    send(store, source, [line() for _ in range(200)] + [line(status=404) for _ in range(40)], "fine")
    run(store)
    assert not problems(store)


def test_a_history_read_in_one_pass_is_not_mistaken_for_one_burst(site):
    store, source = site
    # Ten server errors, one a day, all read now. Dated by the moment they were
    # read they would be a single instant and a burst.
    send(store, source, burst(10, spread=86400, start=time.time() - 12 * 86400))
    run(store)
    assert not problems(store)


def test_a_burst_that_grows_across_scan_passes_stays_one_problem(site):
    store, source = site
    send(store, source, burst(6, start=time.time() - 200), "first")
    run(store)
    assert not problems(store)
    send(store, source, burst(6, start=time.time() - 100), "second")
    run(store)
    (found,) = problems(store)
    assert "12 requests" in found["data"]["summary"]
    send(store, source, burst(4, start=time.time() - 50), "third")
    run(store)
    assert len(problems(store)) == 1


def test_text_chosen_by_the_visitor_is_bounded_and_printable(site):
    store, source = site
    hostile = "/" + "\x1b[31m<script>é" + "a" * 500
    send(store, source, burst(10, target=hostile))
    run(store)
    summary = problems(store)[0]["data"]["summary"]
    assert "\x1b" not in summary and "é" not in summary
    assert "a" * 100 not in summary and "..." in summary
    assert len(summary) < 1500


def test_a_live_burst_alerts(site, monkeypatch):
    store, source = site
    notified = []
    monkeypatch.setattr("logsentinel.portal.notify.enqueue", lambda *args, **kwargs: notified.append(args))
    send(store, source, burst(10), "live")
    run(store)
    assert len(notified) == 1


def test_a_backlog_read_late_still_alerts_when_the_errors_were_recent(site, monkeypatch):
    store, source = site
    notified = []
    monkeypatch.setattr("logsentinel.portal.notify.enqueue", lambda *args, **kwargs: notified.append(args))
    send(store, source, burst(10, start=time.time() - 3600))
    with store.connect() as db:
        db.execute("UPDATE events SET received=?", (time.time() - 3000,))
    run(store)
    assert len(notified) == 1


def test_requests_in_other_sources_do_not_complete_a_burst(site):
    store, source = site
    other = store.get("source", store.put("source", Source(name="api", machine_id=source["machine_id"], kind="push", enabled=True).model_dump()))
    send(store, source, burst(6), "a")
    send(store, other, burst(6), "b")
    run(store)
    assert not problems(store)


PROBES = ["/.env", "/.git/config", "/phpmyadmin/index.php", "/backup.sql", "/vendor/phpunit/src/x.php", "/.aws/credentials"]


def probes(count, *, status=404, ip="203.0.113.9", start=None):
    base = time.time() - 600 if start is None else start
    return [line(ip=ip, status=status, target=PROBES[n % len(PROBES)], when=base + n) for n in range(count)]


def test_repeated_probing_for_sensitive_paths_is_a_quiet_low_finding(site):
    store, source = site
    send(store, source, probes(8) + probes(6, ip="198.51.100.2", start=time.time() - 590), "scan")
    run(store)
    (found,) = problems(store)
    assert found["severity"] == "LOW" and found["data"]["reasoning"] == "web_sensitive_probes"
    summary = found["data"]["summary"]
    assert "14 requests from 2 clients" in summary and "/.env (" in summary and "/phpmyadmin/index.php (" in summary
    assert "203.0.113.9 (8)" in summary


def test_ordinary_traffic_and_a_few_probes_are_not_probing(site):
    store, source = site
    ordinary = ["/index.html", "/api/users", "/.well-known/acme-challenge/token", "/wp-login.php", "/images/old.jpg", "/app.sql.php"]
    send(store, source, [line(target=ordinary[n % len(ordinary)], status=404, when=time.time() - 300 + n) for n in range(60)], "ok")
    send(store, source, probes(9), "few")
    run(store)
    assert not problems(store)


@pytest.mark.parametrize("target", ["/%2e%65nv", "/%252e%2565nv", "/.ENV", "/..%5c.git%5cHEAD", "/.git/config?x=1"])
def test_disguised_requests_for_a_secret_are_still_probes(site, target):
    store, source = site
    send(store, source, [line(status=404, target=target, when=time.time() - 300 + n) for n in range(10)])
    run(store)
    assert [p["data"]["reasoning"] for p in problems(store)] == ["web_sensitive_probes"]


def test_a_query_that_merely_mentions_a_secret_is_not_a_probe(site):
    store, source = site
    send(store, source, [line(status=404, target="/index.php?file=.env", when=time.time() - 300 + n) for n in range(20)])
    run(store)
    assert not problems(store)


@pytest.mark.parametrize("target", ["/.env", "/.git/config", "/backup.sql", "/.env.production", "/id_rsa"])
def test_a_secret_answered_with_success_is_a_finding_at_once(site, target):
    store, source = site
    send(store, source, [line(status=200, target=target)])
    run(store)
    (found,) = problems(store)
    assert found["severity"] == "MEDIUM" and found["data"]["reasoning"] == "web_secret_served"
    assert "catch-all" in found["data"]["summary"] and "(1)" in found["data"]["summary"]


@pytest.mark.parametrize(
    "request_line",
    [
        dict(status=404, target="/.env"),
        dict(status=403, target="/.git/config"),
        dict(status=301, target="/.env"),
        dict(status=200, target="/.env", method="POST"),
        dict(status=200, target="/.well-known/acme-challenge/x"),
        dict(status=200, target="/index.html"),
    ],
)
def test_refused_or_ordinary_requests_are_not_an_exposure(site, request_line):
    store, source = site
    send(store, source, [line(**request_line)])
    run(store)
    assert not [p for p in problems(store) if p["data"]["reasoning"] == "web_secret_served"]


def test_exposures_over_a_day_are_one_problem_that_keeps_updating(site):
    store, source = site
    send(store, source, [line(status=200, target="/.env", when=time.time() - 7200)], "first")
    run(store)
    send(store, source, [line(status=200, target="/.git/config", ip="198.51.100.4", when=time.time() - 60)], "second")
    run(store)
    (found,) = problems(store)
    assert "2 requests from 2 clients" in found["data"]["summary"]


def logins(count, *, ip="203.0.113.9", target="/wp-login.php", status=200, method="POST", start=None, spread=5):
    base = time.time() - 600 if start is None else start
    return [line(ip=ip, status=status, target=target, method=method, when=base + n * spread) for n in range(count)]


def test_one_client_hammering_a_login_page_is_a_high_finding(site):
    store, source = site
    send(store, source, logins(25))
    run(store)
    (found,) = problems(store)
    assert found["severity"] == "HIGH" and found["data"]["category"] == "authentication"
    assert found["data"]["reasoning"] == "web_login_attempts"
    summary = found["data"]["summary"]
    assert "25 requests from 1 clients" in summary and "/wp-login.php (25)" in summary and "203.0.113.9 (25)" in summary
    assert "does not show that any attempt succeeded" in summary


def test_many_visitors_logging_in_is_a_busy_site_not_an_attack(site):
    store, source = site
    crowd = [line(ip=f"198.51.100.{n}", method="POST", target="/login", status=302, when=time.time() - 300 + n) for n in range(1, 61)]
    send(store, source, crowd)
    run(store)
    assert not problems(store)


@pytest.mark.parametrize("busiest, expected", [(14, 0), (15, 1)])
def test_the_busiest_client_must_account_for_fifteen_of_the_attempts(site, busiest, expected):
    store, source = site
    base = time.time() - 600
    # Twelve other visitors: over twenty attempts in one window either way.
    others = [line(ip=f"198.51.100.{n}", method="POST", target="/login", when=base + n) for n in range(1, 13)]
    send(store, source, logins(busiest, target="/login", start=base, spread=3) + others)
    run(store)
    assert len(problems(store)) == expected


def test_fewer_than_twenty_attempts_are_not_a_finding(site):
    store, source = site
    send(store, source, logins(19))
    run(store)
    assert not problems(store)


@pytest.mark.parametrize(
    "request_line",
    [dict(method="GET", target="/login"), dict(method="POST", target="/api/orders"), dict(method="POST", target="/contact"), dict(method="HEAD", target="/wp-login.php")],
)
def test_only_posts_to_login_pages_count(site, request_line):
    store, source = site
    send(store, source, logins(40, **request_line))
    run(store)
    assert not problems(store)


@pytest.mark.parametrize("target", ["/login", "/users/sign_in", "/administrator/index.php", "/api/v2/login", "/xmlrpc.php", "/%6cogin", "/shop/account/login?next=/"])
def test_common_login_pages_are_recognised(site, target):
    store, source = site
    send(store, source, logins(25, target=target))
    run(store)
    assert [p["data"]["reasoning"] for p in problems(store)] == ["web_login_attempts"]
