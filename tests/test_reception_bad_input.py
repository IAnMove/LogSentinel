"""A stranger who can reach the reception port gets a plain refusal, never a crash and a traceback."""

import logging

import pytest
from fastapi.testclient import TestClient

from tests.test_portal_ingest import pair  # noqa: F401


@pytest.mark.parametrize("body", [b"{{", b"", b"\xff\xfe\x00", b'{"events": [', b"nul\x00l"])
def test_malformed_json_is_a_400_without_a_server_error_in_the_log(pair, body, caplog):  # noqa: F811
    panel, reception, source, token, machine = pair
    client = TestClient(reception.app, base_url="https://sentinel.invalid", raise_server_exceptions=False)
    headers = {"Authorization": "Bearer " + token, "Content-Type": "application/json"}
    with caplog.at_level(logging.ERROR):
        refused = [
            client.post("/enroll", content=body, headers={"Content-Type": "application/json"}),
            client.post("/ingest/" + source, content=body, headers=headers),
            client.post("/heartbeat/" + source, content=body, headers=headers),
        ]
    assert [r.status_code for r in refused] == [400, 400, 400], [r.text for r in refused]
    assert all("Traceback" not in r.text for r in refused)
    assert not [r for r in caplog.records if r.exc_info], "a malformed body must not log a stack trace"


def test_a_bad_token_is_still_refused_before_the_body_is_looked_at(pair):  # noqa: F811
    panel, reception, source, token, machine = pair
    client = TestClient(reception.app, base_url="https://sentinel.invalid", raise_server_exceptions=False)
    refused = client.post("/ingest/" + source, content=b"{{", headers={"Authorization": "Bearer wrong", "Content-Type": "application/json"})
    assert refused.status_code == 401


def pause(store, machine):
    paused = store.get("machine", machine)
    paused.pop("id")
    store.put("machine", dict(paused, monitoring_paused=True), machine)


def post_events(pair):
    panel, reception, source, token, machine = pair
    client = TestClient(reception.app, base_url="https://sentinel.invalid", raise_server_exceptions=False)
    return client.post(
        "/ingest/" + source,
        json={"events": [{"id": "e1", "raw": "while paused"}]},
        headers={"Authorization": "Bearer " + token},
    )


def test_a_paused_machine_is_told_so_before_its_body_is_read(pair):  # noqa: F811
    panel, _, _, _, machine = pair
    store = panel.app.state.store
    pause(store, machine)
    answer = post_events(pair)
    assert answer.status_code == 409
    assert answer.json()["detail"]["code"] == "machine_paused"
    assert answer.headers["Retry-After"] == "30"
    assert not store.events(limit=10)


def test_a_machine_paused_while_its_events_are_being_stored_is_a_409_not_a_crash(pair, monkeypatch):  # noqa: F811
    panel, _, _, _, machine = pair
    store = panel.app.state.store
    original = store.ingest

    def paused_in_the_middle(*args, **kwargs):
        # The sender was checked while the machine was active; the pause lands
        # before its events are stored. The window is small but real.
        pause(store, machine)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "ingest", paused_in_the_middle)
    answer = post_events(pair)
    assert answer.status_code == 409, answer.text
    assert "retry" in answer.json()["detail"]
    assert not store.events(limit=10), "nothing is stored while the machine is paused"
