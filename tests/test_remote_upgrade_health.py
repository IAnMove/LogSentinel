"""The central notices outdated senders, failed upgrades and silence after an offer."""

import json
import time

from fastapi.testclient import TestClient

from helpers import machine_source
from logsentinel import __version__
from logsentinel.portal import health as health_module
from logsentinel.portal.ingest import create_ingest_app

COMMIT = "d" * 40


def check(c, key):
    return next(x for x in c.app.state.health.conditions() if x["key"] == key)


def heartbeat(store, source, **sender):
    store.set_meta("health:" + source, json.dumps(dict(status="ok", heartbeat=time.time(), sender=sender)))


def test_an_older_sender_is_a_medium_condition_that_does_not_degrade_liveness(client):
    c, store = client
    machine, source = machine_source(c)
    heartbeat(store, source, build="1.0.0")
    found = check(c, "version:" + source)
    assert found["bad"] and found["severity"] == "MEDIUM" and found["liveness"] is False
    assert found["detail"]["central_version"] == __version__
    heartbeat(store, source, build=__version__)
    assert not check(c, "version:" + source)["bad"]
    heartbeat(store, source, build="99.0")
    assert not check(c, "version:" + source)["bad"]


def test_a_failed_or_refused_upgrade_reported_by_the_host_opens_a_condition(client):
    c, store = client
    machine, source = machine_source(c)
    heartbeat(store, source, build=__version__, upgrade=dict(policy="enabled", status="failed", message="sin espacio", commit=COMMIT))
    found = check(c, "upgrade:" + source)
    assert found["bad"] and found["severity"] == "HIGH" and found["detail"]["message"] == "sin espacio"
    heartbeat(store, source, build=__version__, upgrade=dict(policy="enabled", status="refused", message="no publicado"))
    assert check(c, "upgrade:" + source)["severity"] == "MEDIUM" and check(c, "upgrade:" + source)["bad"]
    heartbeat(store, source, build=__version__, upgrade=dict(policy="enabled", status="installed", commit=COMMIT))
    assert not check(c, "upgrade:" + source)["bad"]


def offer_to(c, store, machine, source, build):
    c.post("/api/settings", json={"remote_upgrade": True}).raise_for_status()
    row = store.get("machine", machine)
    row.pop("id")
    row["remote_upgrade"] = True
    store.put("machine", row, machine)
    token = c.post("/api/sources/" + source + "/token").json()["token"]
    reception = TestClient(create_ingest_app(store, c.app.state.telemetry, build=build), base_url="https://sentinel.invalid")
    answer = reception.get("/sender-control/" + source, headers={"Authorization": "Bearer " + token}).json()
    return answer, reception, token


def test_silence_after_an_offer_is_flagged_without_a_heartbeat_timeout(client, monkeypatch):
    c, store = client
    machine, source = machine_source(c)
    clock = [time.time()]
    monkeypatch.setattr(health_module.time, "time", lambda: clock[0])
    heartbeat(store, source, build="1.0.1")
    answer, reception, token = offer_to(c, store, machine, source, dict(version=__version__, commit=COMMIT, dirty=False))
    assert answer["upgrade"]["commit"] == COMMIT
    assert json.loads(store.meta("upgrade_offer:" + source))["commit"] == COMMIT
    assert not check(c, "upgrade_silence:" + source)["bad"]
    clock[0] += health_module.UPGRADE_SILENCE_SECONDS + 1
    found = check(c, "upgrade_silence:" + source)
    assert found["bad"] and found["severity"] == "HIGH" and found["liveness"] is False
    # The host answers again: the sender is back, whatever it did with the offer.
    store.set_meta("health:" + source, json.dumps(dict(status="ok", heartbeat=clock[0], sender=dict(build="1.0.1"))))
    assert not check(c, "upgrade_silence:" + source)["bad"]
    # Installed and silent afterwards: an ordinary outage, not this condition.
    store.set_meta("health:" + source, json.dumps(dict(status="ok", heartbeat=clock[0], sender=dict(build=__version__, upgrade=dict(policy="enabled", status="installed", commit=COMMIT)))))
    clock[0] += health_module.UPGRADE_SILENCE_SECONDS + 1
    assert not check(c, "upgrade_silence:" + source)["bad"]


def test_a_withdrawn_offer_clears_the_record_and_the_condition(client, monkeypatch):
    c, store = client
    machine, source = machine_source(c)
    answer, reception, token = offer_to(c, store, machine, source, dict(version=__version__, commit=COMMIT, dirty=False))
    assert store.meta("upgrade_offer:" + source)
    c.post("/api/settings", json={"remote_upgrade": False}).raise_for_status()
    reception.get("/sender-control/" + source, headers={"Authorization": "Bearer " + token})
    assert not store.meta("upgrade_offer:" + source)
    clock = [time.time() + 10 * health_module.UPGRADE_SILENCE_SECONDS]
    monkeypatch.setattr(health_module.time, "time", lambda: clock[0])
    assert not check(c, "upgrade_silence:" + source)["bad"]


def test_conditions_are_titled_in_spanish_when_the_panel_is(client):
    c, store = client
    machine, source = machine_source(c)
    c.post("/api/settings", json={"language": "es", "health_grace_seconds": 5}).raise_for_status()
    heartbeat(store, source, build="0.1")
    found = check(c, "version:" + source)
    problem = store.problem(c.app.state.health.report(found))
    assert problem["title"].startswith("Un emisor ejecuta una versión")
