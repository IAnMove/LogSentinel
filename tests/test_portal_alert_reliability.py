"""Severe findings must not be lost to verification gaps, backlogs or outages."""

import json
import time

import httpx
import pytest

from logsentinel.portal.analysis import Analyzer
from logsentinel.portal.models import Destination, Machine, Source
from logsentinel.portal.notify import Outbox
from logsentinel.portal.store import Store


@pytest.fixture
def queue(tmp_path):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="Test host").model_dump())
    sid = store.put(
        "source", Source(name="Test logs", machine_id=machine, kind="push").model_dump()
    )
    return store, store.get("machine", machine), store.get("source", sid)


def configure(store, **changes):
    cfg = store.settings().model_copy(update=changes)
    store.set_meta("settings", cfg.model_dump_json())
    return cfg


def add_destination(store):
    return store.put(
        "destination",
        Destination(name="Alerts", kind="file", enabled=True, min_severity="HIGH").model_dump(),
    )


def deliveries(store):
    return [json.loads(d["payload"]) for d in store.rows("deliveries")]


def triage_high(payload):
    return {
        "findings": [
            dict(
                title=g["message"],
                summary="Operation failed",
                severity="HIGH",
                category="application",
                evidence_ids=[g["id"]],
            )
            for g in payload["groups"]
        ]
    }


def uncertain(payload, severity="HIGH"):
    return {
        "assessments": [
            dict(
                candidate_id=c["candidate_id"],
                status="uncertain",
                severity=severity,
                reason="Context cannot decide",
                evidence_ids=[],
            )
            for c in payload["candidates"]
        ]
    }


@pytest.mark.asyncio
async def test_uncertain_verification_of_a_severe_finding_still_alerts_as_unverified(queue):
    store, machine, source = queue
    configure(store, max_calls=2)
    add_destination(store)
    store.ingest(source, [dict(origin="a", message="disk write failed", service="app")])
    analyzer = Analyzer(store)

    async def model(payload, **kwargs):
        return triage_high(payload) if "groups" in payload else uncertain(payload)

    analyzer.client.call = model
    await analyzer.cycle()
    sent = deliveries(store)
    assert len(sent) == 1
    assert sent[0]["severity"] == "HIGH"
    assert sent[0]["verification_status"] == "uncertain"


@pytest.mark.asyncio
async def test_failed_verification_alerts_after_the_last_attempt(queue, monkeypatch):
    store, machine, source = queue
    configure(store, max_calls=1)
    add_destination(store)
    store.ingest(source, [dict(origin="a", message="oom in worker", service="app")])
    analyzer = Analyzer(store)

    async def model(payload, **kwargs):
        if "groups" in payload:
            return triage_high(payload)
        raise ValueError("malformed verification reply")

    analyzer.client.call = model
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    for _ in range(4):
        clock[0] += 900
        await analyzer.cycle()
        if store.rows("jobs")[0]["status"] == "partial":
            break
    assert store.rows("jobs")[0]["status"] == "partial"
    sent = deliveries(store)
    assert [p["verification_status"] for p in sent] == ["preliminary"]


@pytest.mark.asyncio
async def test_unverified_medium_finding_stays_silent(queue):
    store, machine, source = queue
    configure(store, max_calls=2, verification="all")
    add_destination(store)
    store.ingest(source, [dict(origin="a", message="slow query", service="app")])
    analyzer = Analyzer(store)

    async def model(payload, **kwargs):
        if "groups" in payload:
            return {
                "findings": [
                    dict(
                        title="slow", summary="Slow", severity="MEDIUM",
                        category="application", evidence_ids=[payload["groups"][0]["id"]],
                    )
                ]
            }
        return uncertain(payload, "MEDIUM")

    analyzer.client.call = model
    await analyzer.cycle()
    assert deliveries(store) == []


def backlog(store, source, event_time):
    """One event received long ago (a backlog), stamped with its own time."""
    store.ingest(
        source,
        [dict(origin="a", message="write failed", service="app", timestamp=event_time)],
    )
    with store.connect() as db:
        db.execute("UPDATE events SET received=?", (time.time() - 3600,))


@pytest.mark.asyncio
async def test_late_review_of_a_recent_severe_event_still_alerts(queue):
    store, machine, source = queue
    configure(store, max_calls=2, verification="manual")
    add_destination(store)
    recent = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 1800))
    backlog(store, source, recent)
    analyzer = Analyzer(store)

    async def model(payload, **kwargs):
        return triage_high(payload)

    analyzer.client.call = model
    await analyzer.cycle()
    assert len(deliveries(store)) == 1


@pytest.mark.asyncio
async def test_old_history_stays_silent_even_when_severe(queue):
    store, machine, source = queue
    configure(store, max_calls=2, verification="manual")
    add_destination(store)
    backlog(store, source, "2020-01-01T00:00:00+00:00")
    analyzer = Analyzer(store)

    async def model(payload, **kwargs):
        return triage_high(payload)

    analyzer.client.call = model
    await analyzer.cycle()
    assert len(store.rows("problems")) == 1
    assert deliveries(store) == []


@pytest.mark.asyncio
async def test_late_detector_signal_alerts_only_when_recent_and_severe(queue):
    store, machine, source = queue
    add_destination(store)
    recent = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 600))
    store.ingest(
        source,
        [
            dict(origin="oom", message="Out of memory: Killed process 42", service="kernel", timestamp=recent),
            dict(origin="old", message="Out of memory: Killed process 7", service="kernel", timestamp="2020-01-01T00:00:00+00:00"),
            dict(origin="sudo", message="user NOT in sudoers ; TTY=pts/0", service="sudo", timestamp=recent),
        ],
    )
    with store.connect() as db:
        db.execute("UPDATE events SET received=?", (time.time() - 3600,))
    from logsentinel.portal.signal_scan import scan_originals

    analyzer = Analyzer(store)
    scan_originals(analyzer, machine["id"], store.events(limit=10))
    titles = sorted(p["title"] for p in deliveries(store))
    # The recent OOM is HIGH and alerts late; the sudo signal is MEDIUM and does not.
    assert titles == ["Process killed: out of memory"]


@pytest.mark.asyncio
async def test_provider_outage_does_not_spend_the_attempts_of_a_batch(queue, monkeypatch):
    store, machine, source = queue
    configure(store, max_calls=1)
    store.ingest(source, [dict(origin="a", message="disk write failed", service="app")])
    analyzer = Analyzer(store)
    calls = []

    async def model(payload, **kwargs):
        calls.append(1)
        if len(calls) <= 5:
            raise httpx.ConnectError("provider is down")
        return {"findings": []}

    analyzer.client.call = model
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    for _ in range(8):
        clock[0] += 900
        await analyzer.cycle()
    job = store.rows("jobs")[0]
    assert len(calls) == 6
    assert job["status"] == "done"
    assert job["attempts"] == 1


@pytest.mark.asyncio
async def test_read_timeouts_still_count_because_the_batch_may_be_the_cause(queue, monkeypatch):
    store, machine, source = queue
    configure(store, max_calls=1)
    store.ingest(source, [dict(origin="a", message="disk write failed", service="app")])
    analyzer = Analyzer(store)

    async def model(payload, **kwargs):
        raise httpx.ReadTimeout("model never answered")

    analyzer.client.call = model
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    for _ in range(5):
        clock[0] += 900
        await analyzer.cycle()
    assert store.rows("jobs")[0]["status"] == "failed"


@pytest.mark.asyncio
async def test_unverified_notice_says_so_in_the_message(tmp_path, monkeypatch):
    requests = []

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, text="ok")

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(handler),
            **{k: v for k, v in kw.items() if k != "transport"},
        ),
    )
    store = Store(tmp_path)
    dest = {"kind": "slack", "url": "https://synthetic.invalid/slack"}
    payload = dict(
        severity="HIGH", machine="host", title="Disk failure", summary="Write failed",
        problem_id="p1", delivery_id="d1", verification_status="uncertain",
    )
    await Outbox(store).send(dest, payload)
    assert "Unverified" in requests[0]["text"]
    payload["verification_status"] = "confirmed"
    await Outbox(store).send(dest, payload)
    assert "Unverified" not in requests[1]["text"]


def test_hostile_line_does_not_stop_the_detector_for_its_machine(queue):
    store, machine, source = queue
    add_destination(store)
    hostile = "authentication failure; " + "a" * 262100
    store.ingest(
        source,
        [
            dict(origin="hostile", message=hostile, service="sudo"),
            dict(origin="oom", message="Out of memory: Killed process 42", service="kernel"),
        ],
    )
    from logsentinel.portal.signal_scan import scan_originals

    analyzer = Analyzer(store)
    scan_originals(analyzer, machine["id"], store.events(limit=10))
    assert [p["title"] for p in store.rows("problems")] == ["Process killed: out of memory"]
    with store.connect() as db:
        scanned = db.execute("SELECT count(*) FROM signal_scans").fetchone()[0]
    assert scanned == 2


@pytest.mark.parametrize("service", ["sshd", "sshd-session", "sshd-auth", "sshd.service"])
def test_ssh_burst_is_detected_for_every_openssh_process_name(queue, service):
    store, machine, source = queue
    store.ingest(
        source,
        [
            dict(origin=str(i), message=f"Failed password for root from 203.0.113.5 port {2000 + i} ssh2", service=service)
            for i in range(6)
        ],
    )
    from logsentinel.portal.signal_scan import scan_originals

    scan_originals(Analyzer(store), machine["id"], store.events(limit=10))
    assert [p["title"] for p in store.rows("problems")] == ["Repeated SSH authentication rejections"]


@pytest.mark.parametrize(
    "message",
    [
        "sudo: pam_unix(sudo:auth): authentication failure; logname=ina uid=1000 euid=0 tty=/dev/pts/1 ruser=ina rhost= user=ina",
        "sudo: 3 incorrect password attempts ; TTY=pts/0 ; PWD=/home/user ; USER=root ; COMMAND=/usr/bin/ls",
        "sudo: ina : user NOT in sudoers ; TTY=pts/0",
    ],
)
def test_sudo_rejections_are_recognised(queue, message):
    store, machine, source = queue
    store.ingest(source, [dict(origin="a", message=message, service="sudo")])
    from logsentinel.portal.signal_scan import scan_originals

    scan_originals(Analyzer(store), machine["id"], store.events(limit=10))
    assert [p["title"] for p in store.rows("problems")] == ["sudo authentication rejected"]


def test_regex_timeout_on_one_line_is_counted_and_detection_continues(queue, monkeypatch):
    store, machine, source = queue
    store.ingest(
        source,
        [
            dict(origin="slow", message="pathological line", service="app"),
            dict(origin="oom", message="Out of memory: Killed process 42", service="kernel"),
        ],
    )
    from logsentinel.portal import signals
    from logsentinel.portal.signal_scan import scan_originals

    real = signals.regex.search

    def search(pattern, text, **kwargs):
        if text == "pathological line":
            raise TimeoutError("synthetic")
        return real(pattern, text, **kwargs)

    monkeypatch.setattr(signals.regex, "search", search)
    scan_originals(Analyzer(store), machine["id"], store.events(limit=10))
    assert [p["title"] for p in store.rows("problems")] == ["Process killed: out of memory"]
    assert int(store.meta("detector_slow_lines")) == sum(1 for s in signals.SIGNALS if not s.get("service"))
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM signal_scans").fetchone()[0] == 2


def statements(store):
    """Record every SQL statement the store runs, to see what a pass costs."""
    log = []
    original = store.connect

    from contextlib import contextmanager

    @contextmanager
    def tracing():
        with original() as db:
            db.set_trace_callback(log.append)
            yield db

    store.connect = tracing
    return log


def test_an_idle_machine_costs_no_history_scan_until_something_arrives(queue):
    from logsentinel.portal.signal_scan import scan_signals

    store, machine, source = queue
    analyzer = Analyzer(store)
    store.ingest(source, [dict(origin="a", message="Out of memory: Killed process 42", service="kernel")])
    assert scan_signals(analyzer) == 1
    assert store.rows("problems")  # the first pass did its job

    log = statements(store)
    assert scan_signals(analyzer) == 0  # discovers there is nothing left, once
    assert any("signal_scans" in s and "LEFT JOIN" in s for s in log)
    log.clear()
    for _ in range(3):
        assert scan_signals(analyzer) == 0
    assert not any("LEFT JOIN" in s for s in log)  # idle: no scan of the machine's events

    store.ingest(source, [dict(origin="b", message="No space left on device", service="kernel")])
    log.clear()
    assert scan_signals(analyzer) == 1  # new data wakes it
    assert any("LEFT JOIN" in s for s in log)


def test_a_failed_pass_is_retried_and_never_marked_idle(queue, monkeypatch):
    from logsentinel.portal import signal_scan

    store, machine, source = queue
    store.ingest(source, [dict(origin="a", message="Out of memory: Killed process 42", service="kernel")])
    real = signal_scan.scan_originals
    calls = []

    def flaky(analyzer, machine_id, events):
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("synthetic detector failure")
        return real(analyzer, machine_id, events)

    monkeypatch.setattr(signal_scan, "scan_originals", flaky)
    analyzer = Analyzer(store)
    signal_scan.scan_signals(analyzer)
    assert store.meta("signal_idle:" + machine["id"]) is None
    assert signal_scan.scan_signals(analyzer) == 1
    assert len(calls) == 2
