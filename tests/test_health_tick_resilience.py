"""A failure while recording one health condition does not stop the tick or stale the snapshot."""

import json
import sqlite3
import time

from tests.helpers import machine_source


def test_a_failing_report_leaves_the_tick_whole_and_the_snapshot_fresh(client, monkeypatch):
    c, store = client
    machine, source = machine_source(c)
    store.set_meta("health:" + source, json.dumps(dict(status="error", heartbeat=time.time(), error="Sender capture failed")))
    settings = store.settings()
    settings.health_grace_seconds = 5  # the smallest grace allowed
    store.set_meta("settings", settings.model_dump_json())
    health = c.app.state.health

    def broken(check, recovered=False, notify=True):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(health, "report", broken)
    health.tick()  # the condition starts its grace period
    from logsentinel.portal import health as module

    later = time.time() + 30
    monkeypatch.setattr(module.time, "time", lambda: later)
    snapshot = health.tick()  # past the grace: report() is called and fails
    assert snapshot["checked"] == later, "the tick completed and refreshed the snapshot"
    failing = next(check for check in snapshot["checks"] if check["key"] == "source:" + source)
    assert failing["bad"] and "OperationalError" in failing.get("persistence_error", "")
    assert health.state()["state"] != "stale"
