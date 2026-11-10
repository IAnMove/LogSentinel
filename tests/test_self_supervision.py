"""The observer notices when it has stopped observing, and does not read itself."""

import json
import logging
import logging.config
import time

from helpers import machine_source
from logsentinel.portal.health import (
    ANALYSIS_OFF_SECONDS,
    NEVER_CONNECTED_SECONDS,
    REMINDER_SECONDS,
)
from logsentinel.portal.logs import FailedRequestsOnly, uvicorn_log_config


def access(status):
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
        ("192.0.2.7:4000", "POST", "/ingest/abc", "1.1", status), None,
    )


def test_successful_requests_are_not_logged_and_refusals_are():
    quiet = FailedRequestsOnly()
    assert not quiet.filter(access(200))
    assert not quiet.filter(access(304))
    assert quiet.filter(access(401))
    assert quiet.filter(access(507))
    # A record of another shape is never lost to the filter.
    assert quiet.filter(logging.LogRecord("uvicorn.access", logging.INFO, "", 0, "started", None, None))


def test_the_server_logging_configuration_carries_the_filter():
    config = uvicorn_log_config()
    assert config["handlers"]["access"]["filters"] == ["failed_requests_only"]
    saved = logging.getLogger("uvicorn.access").handlers[:]
    try:
        logging.config.dictConfig(config)
        handler = logging.getLogger("uvicorn.access").handlers[0]
        assert any(isinstance(f, FailedRequestsOnly) for f in handler.filters)
    finally:
        logging.getLogger("uvicorn.access").handlers[:] = saved


def switch(store, enabled):
    store.set_meta(
        "settings", store.settings().model_copy(update=dict(enabled=enabled)).model_dump_json()
    )


def check(health, key):
    return next(c for c in health.conditions() if c["key"] == key)


def test_a_source_no_sender_ever_reached_is_reported(client, monkeypatch):
    c, store = client
    machine, source = machine_source(c)
    health = c.app.state.health
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    assert not check(health, "never_connected:" + source)["bad"]
    clock[0] += NEVER_CONNECTED_SECONDS + 1
    found = check(health, "never_connected:" + source)
    assert found["bad"] and found["machine_id"] == machine
    # One delivery or heartbeat is enough: after that, silence is the
    # heartbeat timeout's business, not this check's.
    store.set_meta("health:" + source, json.dumps(dict(status="ok", checked=clock[0])))
    assert not check(health, "never_connected:" + source)["bad"]


def test_analysis_left_off_is_reported_after_a_day(client, monkeypatch):
    c, store = client
    machine_source(c)
    health = c.app.state.health
    store.set_meta("setup_completed", str(time.time()))
    assert not store.settings().enabled
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    assert not check(health, "analysis_off")["bad"]
    clock[0] += ANALYSIS_OFF_SECONDS + 1
    assert check(health, "analysis_off")["bad"]
    switch(store, True)
    assert not check(health, "analysis_off")["bad"]
    # Off again starts a new day; the old one is not held against it.
    switch(store, False)
    assert not check(health, "analysis_off")["bad"]


def test_an_unfinished_setup_is_not_a_forgotten_pause(client, monkeypatch):
    c, store = client
    machine_source(c)
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    check(c.app.state.health, "analysis_off")
    clock[0] += ANALYSIS_OFF_SECONDS * 3
    assert not check(c.app.state.health, "analysis_off")["bad"]


def test_a_condition_that_stays_bad_is_announced_again_each_day(client, monkeypatch):
    c, store = client
    machine, source = machine_source(c)
    health = c.app.state.health
    reports = []
    original = health.report

    def counted(found, recovered=False, notify=True):
        reports.append((found["key"], recovered))
        return original(found, recovered=recovered, notify=notify)

    monkeypatch.setattr(health, "report", counted)
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    store.set_meta(
        "health:" + source,
        json.dumps(dict(status="error", heartbeat=clock[0], error="Sender capture failed")),
    )
    key = "source:" + source
    health.tick()
    clock[0] += 60
    health.tick()
    assert reports.count((key, False)) == 1
    clock[0] += 3600
    health.tick()
    assert reports.count((key, False)) == 1  # not every tick
    clock[0] += REMINDER_SECONDS
    health.tick()
    assert reports.count((key, False)) == 2
    assert len([p for p in store.rows("problems") if p["status"] == "open"]) == 1
