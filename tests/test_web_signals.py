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
