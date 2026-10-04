"""A realistic access log, read from a file, shows the right problems and no others."""

import json
import random
import time

import pytest

from logsentinel.portal.analysis import Analyzer
from logsentinel.portal.collect import Collector
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.signal_scan import scan_signals
from logsentinel.portal.store import Store
from tests.test_web_signals import line


def traffic(now):
    """Ten quiet minutes of a small site, with five different troubles in them."""
    rng = random.Random(7)
    pages = ["/", "/about", "/blog", "/blog/first-post", "/contact", "/static/app.css", "/static/app.js", "/favicon.ico"]
    visitors = [f"198.51.100.{n}" for n in range(100, 140)]
    rows = []
    for n in range(400):
        status = rng.choices([200, 304, 404], weights=[85, 12, 3])[0]
        rows.append((now - 600 + n * 1.4, line(ip=rng.choice(visitors), status=status, target=rng.choice(pages) if status != 404 else f"/old/{n}", when=now - 600 + n * 1.4)))
    # A scanner: seventy different missing paths, twelve of them for secrets, and one catch-all answer.
    secrets = ["/.env", "/.git/config", "/backup.sql", "/.aws/credentials", "/phpmyadmin/", "/vendor/phpunit/x.php"] * 2
    for n in range(70):
        target = secrets[n] if n < len(secrets) else f"/admin{n}/login.php"
        rows.append((now - 500 + n, line(ip="203.0.113.9", status=404, target=target, when=now - 500 + n)))
    rows.append((now - 420, line(ip="203.0.113.9", status=200, target="/.env", when=now - 420)))
    # Credential stuffing against WordPress.
    rows += [(now - 400 + n * 3, line(ip="198.51.100.50", method="POST", status=200, target="/wp-login.php", when=now - 400 + n * 3)) for n in range(40)]
    # Injection attempts, one of them answered 500.
    for n in range(8):
        rows.append((now - 300 + n, line(ip="192.0.2.99", status=500 if n == 3 else 400, target="/item?id=1%20UNION%20SELECT%20password%20FROM%20users", when=now - 300 + n)))
    # The application failing.
    rows += [(now - 200 + n, line(ip=visitors[n], status=502, target="/api/orders", when=now - 200 + n)) for n in range(12)]
    return [text for _, text in sorted(rows)]


def test_a_realistic_access_log_gives_the_expected_problems_and_never_reaches_the_model(tmp_path):
    store = Store(tmp_path / "data")
    machine = store.put("machine", Machine(name="Web host").model_dump())
    log = tmp_path / "access.log"
    log.write_text("\n".join(traffic(time.time())) + "\n")
    sid = store.put("source", Source(name="nginx", machine_id=machine, kind="file", path=str(log), enabled=True, history=True).model_dump())
    assert Collector(store).poll(store.get("source", sid)) == 400 + 70 + 1 + 40 + 8 + 12

    analyzer = Analyzer(store)
    while scan_signals(analyzer):
        pass
    found = {json.loads(p["data"])["reasoning"]: p for p in store.rows("problems")}
    assert set(found) == {
        "web_server_errors",
        "web_sensitive_probes",
        "web_secret_served",
        "web_login_attempts",
        "web_path_enumeration",
        "web_attack_payloads",
    }
    severities = {name: p["severity"] for name, p in found.items()}
    assert severities == {
        "web_server_errors": "HIGH",
        "web_login_attempts": "HIGH",
        "web_secret_served": "MEDIUM",
        "web_attack_payloads": "LOW",
        "web_sensitive_probes": "LOW",
        "web_path_enumeration": "LOW",
    }
    assert "198.51.100.50 (40)" in json.loads(found["web_login_attempts"]["data"])["summary"]
    assert "203.0.113.9" in json.loads(found["web_path_enumeration"]["data"])["summary"]
    assert "500 (1)" in json.loads(found["web_attack_payloads"]["data"])["summary"]

    sent = []

    async def record(payload, **kwargs):
        sent.append(payload)
        return {"findings": []}

    analyzer.client.call = record
    import asyncio

    assert asyncio.run(analyzer.cycle()) == {"calls": 0, "errors": 0}
    assert not sent
    assert {e["status"] for e in store.events(limit=5000)} == {"sampled"}


def test_quiet_traffic_on_its_own_raises_nothing(tmp_path):
    store = Store(tmp_path / "data")
    machine = store.put("machine", Machine(name="Web host").model_dump())
    rng = random.Random(3)
    now = time.time()
    quiet = [
        line(ip=f"198.51.100.{rng.randint(1, 200)}", status=rng.choices([200, 304, 404, 301], weights=[80, 10, 6, 4])[0],
             target=rng.choice(["/", "/blog", "/shop", "/static/a.css", "/robots.txt", "/missing"]), when=now - 3000 + n * 2)
        for n in range(1200)
    ]
    log = tmp_path / "access.log"
    log.write_text("\n".join(quiet) + "\n")
    sid = store.put("source", Source(name="nginx", machine_id=machine, kind="file", path=str(log), enabled=True, history=True).model_dump())
    collector, source = Collector(store), store.get("source", sid)
    # A pass reads at most a thousand lines.
    assert sum(collector.poll(source) for _ in range(3)) == 1200
    while scan_signals(Analyzer(store)):
        pass
    assert not store.rows("problems")
