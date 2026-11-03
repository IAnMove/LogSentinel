"""The central offers senders its own build; the offer needs both switches and a pushed commit."""

import json

from fastapi.testclient import TestClient

from logsentinel.portal.ingest import create_ingest_app
from tests.test_portal_ingest import pair  # noqa: F401

COMMIT = "b" * 40


def control(panel, source, token, build):
    reception = TestClient(
        create_ingest_app(panel.app.state.store, panel.app.state.telemetry, build=build),
        base_url="https://sentinel.invalid",
    )
    answer = reception.get("/sender-control/" + source, headers={"Authorization": "Bearer " + token})
    assert answer.status_code == 200, answer.text
    return answer.json()


def switch_on(panel, machine, central=True, this_machine=True):
    assert panel.post("/api/settings", json={"remote_upgrade": central}).status_code == 200
    data = panel.get("/api/state").json()["machine"]
    (row,) = [m for m in data if m["id"] == machine]
    row["remote_upgrade"] = this_machine
    saved = panel.post("/api/objects/machine", json=row)
    assert saved.status_code == 200, saved.text


def test_nothing_is_offered_by_default_but_the_key_is_there(pair):  # noqa: F811
    panel, reception, source, token, machine = pair
    answer = reception.get("/sender-control/" + source, headers={"Authorization": "Bearer " + token}).json()
    assert "upgrade" in answer and answer["upgrade"] is None


def test_both_switches_and_a_clean_commit_make_an_offer(pair):  # noqa: F811
    panel, reception, source, token, machine = pair
    build = dict(version="9.9.9", commit=COMMIT, dirty=False)
    switch_on(panel, machine)
    assert control(panel, source, token, build)["upgrade"] == dict(version="9.9.9", commit=COMMIT)


def test_either_switch_off_withdraws_the_offer(pair):  # noqa: F811
    panel, reception, source, token, machine = pair
    build = dict(version="9.9.9", commit=COMMIT, dirty=False)
    switch_on(panel, machine, central=False, this_machine=True)
    assert control(panel, source, token, build)["upgrade"] is None
    switch_on(panel, machine, central=True, this_machine=False)
    assert control(panel, source, token, build)["upgrade"] is None


def test_a_dirty_or_unknown_checkout_is_never_offered(pair):  # noqa: F811
    panel, reception, source, token, machine = pair
    switch_on(panel, machine)
    assert control(panel, source, token, dict(version="9.9.9", commit=COMMIT, dirty=True))["upgrade"] is None
    assert control(panel, source, token, dict(version="9.9.9", commit=None, dirty=None))["upgrade"] is None


def test_the_machine_switch_is_off_for_existing_machines(pair):  # noqa: F811
    panel, reception, source, token, machine = pair
    store = panel.app.state.store
    assert store.get("machine", machine)["remote_upgrade"] is False
    assert json.loads(store.meta("settings") or "{}").get("remote_upgrade", False) is False
