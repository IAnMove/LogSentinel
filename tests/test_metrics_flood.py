"""A metrics token lets a sender report its own disks, not open a problem per invented key."""

import json

import pytest
from fastapi.testclient import TestClient

from logsentinel.portal.app import create_app
from logsentinel.portal.ingest import create_ingest_app


@pytest.fixture
def metrics(tmp_path):
    app = create_app(tmp_path, background=False)
    with TestClient(app, base_url="http://localhost") as panel:
        panel.headers["X-LogSentinel"] = "portal"
        panel.post("/login", json={"token": app.state.store.meta("admin_token")})
        machine = panel.post("/api/objects/machine", json={"name": "A"}).json()["id"]
        panel.post("/api/objects/destination", json={"name": "Archivo", "kind": "file", "enabled": True, "min_severity": "LOW"})
        panel.post(f"/api/telemetry/{machine}/config", json={"enabled": True, "mode": "remote"})
        token = panel.post(f"/api/telemetry/{machine}/token").json()["token"]
        reception = TestClient(create_ingest_app(app.state.store, app.state.telemetry), base_url="https://sentinel.invalid", raise_server_exceptions=False)

        def post(samples):
            return reception.post(f"/ingest-metrics/{machine}", json={"samples": samples}, headers={"Authorization": "Bearer " + token})

        yield panel, app.state.store, machine, post


def disks(mounts):
    return [{"mount": m} for m in mounts]


def test_a_hundred_invented_disks_in_one_sample_are_refused(metrics):
    panel, store, machine, post = metrics
    values = {f"disk_pct:/mnt/x{n}": 99 for n in range(100)}
    answer = post([{"values": values}])
    assert answer.status_code in (400, 422), answer.text
    assert not store.rows("problems")


def test_a_disk_key_must_belong_to_a_listed_mount_when_mounts_are_listed(metrics):
    panel, store, machine, post = metrics
    answer = post([{"values": {"disk_pct:/": 40, "disk_pct:/mnt/ghost": 99}, "disks": disks(["/"])}])
    assert answer.status_code in (400, 422), answer.text
    ok = post([{"values": {"disk_pct:/": 40, "disk_pct:/mnt/data": 50}, "disks": disks(["/", "/mnt/data"])}])
    assert ok.status_code == 200, ok.text


def test_an_old_sender_that_lists_no_mounts_is_still_accepted_within_the_cap(metrics):
    panel, store, machine, post = metrics
    answer = post([{"values": {f"disk_pct:/mnt/d{n}": 50 for n in range(16)}}])
    assert answer.status_code == 200, answer.text


def test_the_problems_one_machine_can_open_per_hour_are_bounded(metrics):
    panel, store, machine, post = metrics
    # Each sample is valid on its own: sixteen mounts it declares, all critical.
    for batch in range(5):
        samples = []
        for s in range(4):
            mounts = [f"/mnt/v{batch}-{s}-{n}" for n in range(16)]
            samples.append({"values": {f"disk_pct:{m}": 99 for m in mounts}, "disks": disks(mounts)})
        answer = post(samples)
        assert answer.status_code == 200, answer.text
    opened = len(store.rows("problems"))
    assert opened <= 25, f"{opened} problems from one token in a moment"
    assert "budget" in (store.meta("telemetry_error:" + machine) or "").lower()


def test_metrics_reception_is_held_to_the_sender_quota(metrics):
    panel, store, machine, post = metrics
    settings = store.settings()
    settings.sender_events_per_hour = 100  # the smallest allowance allowed
    store.set_meta("settings", settings.model_dump_json())
    for _ in range(5):
        assert post([{"values": {"cpu_pct": 1}}] * 20).status_code == 200
    throttled = post([{"values": {"cpu_pct": 1}}])
    assert throttled.status_code == 429 and int(throttled.headers["Retry-After"]) > 0
