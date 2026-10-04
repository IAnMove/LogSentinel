"""An access line becomes an event dated and described by what the server logged."""

import gzip
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from logsentinel.portal.app import create_app
from logsentinel.portal.collect import Collector, normalize
from logsentinel.portal.ingest import create_ingest_app
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store

LINE = (
    '192.0.2.10 - - [10/Oct/2026:13:55:36 +0200] "GET /.env HTTP/1.1" 404 153 '
    '"-" "curl/8.0"'
)


def test_a_web_request_is_dated_by_the_server_and_carries_its_fields():
    event = normalize(LINE, "/var/log/nginx/access.log", "o1")
    assert event["timestamp"].startswith("2026-10-10T11:55:36")
    assert event["service"] == "web-access"
    assert event["message"] == LINE and event["raw"] == LINE
    assert event["metadata"]["timestamp_inferred"] is False
    assert event["metadata"]["web"]["ip"] == "192.0.2.10"
    assert event["metadata"]["web"]["status"] == 404
    assert event["metadata"]["web"]["target"] == "/.env"


def test_an_ordinary_line_is_left_exactly_as_before():
    plain = "Oct 10 13:55:36 host app[7]: GET /.env 404"
    event = normalize(plain, "/var/log/app.log", "o2")
    assert "web" not in event["metadata"]
    assert event["service"] == "app"


def test_a_request_forwarded_through_syslog_is_recognised():
    event = normalize("Oct 10 13:55:40 host nginx: " + LINE, "/var/log/syslog", "o3")
    assert event["metadata"]["web"]["status"] == 404
    assert event["service"] == "web-access"
    assert event["timestamp"].startswith("2026-10-10T11:55:36")


@pytest.fixture
def folder(tmp_path):
    store = Store(tmp_path / "data")
    machine = store.put("machine", Machine(name="A").model_dump())
    logs = tmp_path / "logs"
    logs.mkdir()
    source = dict(
        Source(
            machine_id=machine, name="web", kind="folder", path=str(logs),
            pattern="access.log*", enabled=True, history=True,
        ).model_dump(),
        id="s",
    )
    return store, source, logs


def test_an_imported_history_keeps_the_dates_the_server_wrote(folder):
    store, source, logs = folder
    old = LINE.replace("10/Oct/2026", "03/Mar/2020")
    (logs / "access.log").write_text(LINE + "\n" + old + "\nnot a request\n")
    (logs / "access.log.1.gz").write_bytes(gzip.compress((old.replace("03/Mar", "04/Mar") + "\n").encode()))
    collector = Collector(store)
    # The collector reads one file per pass, newest first.
    assert sum(collector.poll(source) for _ in range(3)) == 4
    events = store.events(limit=100)
    dated = sorted(e["event_time"][:10] for e in events if e["service"] == "web-access")
    assert dated == ["2020-03-03", "2020-03-04", "2026-10-10"]
    assert [e["message"] for e in events if e["service"] != "web-access"] == ["not a request"]
    assert all(e["metadata"]["web"]["status"] == 404 for e in events if e["service"] == "web-access")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    assert now not in dated


def test_a_remote_sender_gets_the_same_treatment(tmp_path):
    app = create_app(tmp_path, background=False)
    with TestClient(app, base_url="http://localhost") as panel:
        panel.headers["X-LogSentinel"] = "portal"
        panel.post("/login", json={"token": app.state.store.meta("admin_token")})
        machine = panel.post("/api/objects/machine", json={"name": "A"}).json()["id"]
        source = panel.post(
            "/api/objects/source",
            json={"name": "remote", "machine_id": machine, "kind": "push", "enabled": True},
        ).json()["id"]
        token = panel.post("/api/sources/" + source + "/token").json()["token"]
        reception = TestClient(
            create_ingest_app(app.state.store, app.state.telemetry),
            base_url="https://sentinel.invalid",
        )
        sent = reception.post(
            "/ingest/" + source,
            json={"events": [{"id": "e1", "raw": LINE}]},
            headers={"Authorization": "Bearer " + token},
        )
        assert sent.status_code == 200, sent.text
        (event,) = app.state.store.events(source_id=source)
        assert event["service"] == "web-access"
        assert event["event_time"].startswith("2026-10-10T11:55:36")
        assert event["metadata"]["web"]["target"] == "/.env"
