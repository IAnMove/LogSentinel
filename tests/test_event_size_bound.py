"""Nothing the collector stores is bigger than what the receiver accepts."""

import pytest
from fastapi.testclient import TestClient

from logsentinel.portal.app import create_app
from logsentinel.portal.collect import MAX_LINE, Collector
from logsentinel.portal.ingest import create_ingest_app
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store


@pytest.fixture
def file_source(tmp_path):
    store = Store(tmp_path / "data")
    machine = store.put("machine", Machine(name="A").model_dump())
    path = tmp_path / "app.log"

    def make(**extra):
        return dict(Source(machine_id=machine, name="app", kind="file", path=str(path), enabled=True, history=True, **extra).model_dump(), id="s")

    return store, path, make


def drain(store, source):
    collector = Collector(store)
    total = sum(collector.poll(source) for _ in range(6))
    collector.close()
    return total


def biggest(store):
    return max(len(e["raw"].encode()) for e in store.events(limit=100))


def test_a_multiline_trace_is_cut_to_the_limit_and_says_so(file_source):
    store, path, make = file_source
    path.write_text("ERROR boom\n" + ("    at frame" + "x" * 1000 + "\n") * 400 + "next line\n")
    assert drain(store, make(multiline=True)) == 2
    events = store.events(limit=10)
    trace, after = events
    assert len(trace["raw"].encode()) <= MAX_LINE
    assert "line cut" in trace["message"] and trace["metadata"]["cut_bytes"] > 100_000
    assert trace["message"].startswith("ERROR boom\n    at frame")
    assert after["message"] == "next line"


def test_bytes_that_grow_when_decoded_are_cut_to_the_limit(file_source):
    store, path, make = file_source
    # 100 000 invalid bytes decode to 300 000 bytes of U+FFFD.
    path.write_bytes(b"\xff" * 100_000 + b"\nok\n")
    assert drain(store, make()) == 2
    first, second = store.events(limit=10)
    assert len(first["raw"].encode()) <= MAX_LINE and "line cut" in first["message"]
    assert first["metadata"]["cut_bytes"] > 0
    assert second["message"] == "ok"


def test_a_cut_continuation_line_is_counted(file_source):
    store, path, make = file_source
    path.write_text("ERROR start\n    " + "z" * 300_000 + "\nafter\n")
    assert drain(store, make(multiline=True)) == 2
    first, second = store.events(limit=10)
    assert first["metadata"]["cut_bytes"] > 0 and len(first["raw"].encode()) <= MAX_LINE
    assert second["message"] == "after"


def test_an_ordinary_line_is_untouched(file_source):
    store, path, make = file_source
    path.write_text("plain\n" + "x" * 200_000 + "\n")
    assert drain(store, make()) == 2
    for event in store.events(limit=10):
        assert "cut_bytes" not in event["metadata"] and "line cut" not in event["message"]


def test_what_the_collector_stores_is_what_the_receiver_accepts(tmp_path):
    app = create_app(tmp_path / "central", background=False)
    with TestClient(app, base_url="http://localhost") as panel:
        panel.headers["X-LogSentinel"] = "portal"
        panel.post("/login", json={"token": app.state.store.meta("admin_token")})
        machine = panel.post("/api/objects/machine", json={"name": "A"}).json()["id"]
        sid = panel.post("/api/objects/source", json={"name": "remote", "machine_id": machine, "kind": "push", "enabled": True}).json()["id"]
        token = panel.post("/api/sources/" + sid + "/token").json()["token"]
        reception = TestClient(create_ingest_app(app.state.store, app.state.telemetry), base_url="https://sentinel.invalid")
        # A sender's own collector, with the sender's capture settings.
        store = Store(tmp_path / "sender")
        m = store.put("machine", Machine(name="S").model_dump())
        path = tmp_path / "trace.log"
        path.write_text("ERROR boom\n" + ("    at frame" + "x" * 1000 + "\n") * 400 + "\n" + "tail\n")
        path.write_bytes(path.read_bytes() + b"\xff" * 100_000 + b"\n")
        source = dict(Source(machine_id=m, name="s", kind="file", path=str(path), enabled=True, history=True, multiline=True).model_dump(), id="s")
        drain(store, source)
        events = store.events(limit=100)
        assert len(events) >= 3
        sent = reception.post("/ingest/" + sid, json={"events": [{"id": e["id"], "raw": e["raw"]} for e in events]}, headers={"Authorization": "Bearer " + token})
        assert sent.status_code == 200, sent.text
        assert sent.json()["accepted"] == len(events)


def test_the_receiver_cuts_an_oversized_event_instead_of_refusing_the_batch(tmp_path):
    app = create_app(tmp_path / "central", background=False)
    with TestClient(app, base_url="http://localhost") as panel:
        panel.headers["X-LogSentinel"] = "portal"
        panel.post("/login", json={"token": app.state.store.meta("admin_token")})
        machine = panel.post("/api/objects/machine", json={"name": "A"}).json()["id"]
        sid = panel.post("/api/objects/source", json={"name": "remote", "machine_id": machine, "kind": "push", "enabled": True}).json()["id"]
        token = panel.post("/api/sources/" + sid + "/token").json()["token"]
        reception = TestClient(create_ingest_app(app.state.store, app.state.telemetry), base_url="https://sentinel.invalid", raise_server_exceptions=False)
        headers = {"Authorization": "Bearer " + token}
        big = "ERROR boom\n" + ("    at frame" + "x" * 1000 + "\n") * 300
        sent = reception.post("/ingest/" + sid, json={"events": [{"id": "a", "raw": "before"}, {"id": "b", "raw": big}, {"id": "c", "raw": "after"}]}, headers=headers)
        assert sent.status_code == 200, sent.text
        assert sent.json()["accepted"] == 3
        stored = {e["origin"]: e for e in app.state.store.events(limit=10)}
        assert len(stored["b"]["raw"].encode()) <= MAX_LINE and "line cut" in stored["b"]["message"]
        assert stored["a"]["message"] == "before" and stored["c"]["message"] == "after"
        # Beyond four times the limit the item is not a log line; the batch is refused.
        refused = reception.post("/ingest/" + sid, json={"events": [{"id": "d", "raw": "y" * (4 * MAX_LINE + 1)}]}, headers=headers)
        assert refused.status_code == 400
