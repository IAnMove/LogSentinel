"""The reception listener carries reception and nothing that administers the portal."""
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from logsentinel import cli
from logsentinel.portal.app import create_app
from logsentinel.portal.ingest import create_ingest_app


@pytest.fixture
def pair(tmp_path):
    """A portal and a reception listener over one store, plus a live source token."""
    app = create_app(tmp_path, background=False)
    with TestClient(app, base_url="http://localhost") as panel:
        panel.post("/login", json={"token": app.state.store.meta("admin_token")})
        panel.headers["X-LogSentinel"] = "portal"
        machine = panel.post("/api/objects/machine", json={"name": "A"}).json()["id"]
        source = panel.post(
            "/api/objects/source",
            json={"name": "remote", "machine_id": machine, "kind": "push", "enabled": True},
        ).json()["id"]
        token = panel.post("/api/sources/" + source + "/token").json()["token"]
        reception = TestClient(create_ingest_app(app.state.store), base_url="https://sentinel.invalid")
        yield panel, reception, source, token


ADMIN_PATHS = ["/", "/api/state", "/api/stats", "/api/settings", "/login", "/api/backup"]


@pytest.mark.parametrize("path", ADMIN_PATHS)
def test_reception_listener_exposes_no_administration(pair, path):
    _, reception, _, _ = pair
    assert reception.get(path).status_code == 404
    assert reception.post(path, json={}).status_code == 404


def test_reception_accepts_a_token_holder_from_any_host(pair):
    _, reception, source, token = pair
    headers = {"Authorization": "Bearer " + token}
    body = {"events": [{"id": "e1", "raw": "synthetic reception line"}]}
    result = reception.post("/ingest/" + source, json=body, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["accepted"] == 1
    assert reception.post(
        "/heartbeat/" + source, json={"ok": True, "pending": 0}, headers=headers
    ).status_code == 200


def test_reception_still_requires_the_source_token(pair):
    _, reception, source, _ = pair
    body = {"events": [{"id": "e1", "raw": "synthetic reception line"}]}
    assert reception.post("/ingest/" + source, json=body).status_code == 401
    assert reception.post(
        "/ingest/" + source, json=body, headers={"Authorization": "Bearer wrong"}
    ).status_code == 401


def test_portal_keeps_serving_reception_for_existing_tunnels(pair):
    panel, _, source, token = pair
    body = {"events": [{"id": "e1", "raw": "synthetic tunnel line"}]}
    result = panel.post(
        "/ingest/" + source, json=body, headers={"Authorization": "Bearer " + token}
    )
    assert result.status_code == 200, result.text


def test_reception_rejects_an_oversized_request(pair):
    _, reception, source, token = pair
    oversized = "x" * 5_000_000
    result = reception.post(
        "/ingest/" + source,
        content=('{"events": [{"id": "e1", "raw": "' + oversized + '"}]}').encode(),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    assert result.status_code == 413


@pytest.mark.parametrize(
    "flags",
    [
        ["--ingest-listen", "0.0.0.0:8767"],
        ["--tls-cert", "/nonexistent.pem", "--tls-key", "/nonexistent.key"],
        ["--ingest-listen", "0.0.0.0:8767", "--tls-cert", "/nonexistent.pem"],
        ["--ingest-listen", "not-a-port", "--tls-cert", "a", "--tls-key", "b"],
    ],
)
def test_portal_refuses_an_unprotected_or_incomplete_reception_listener(tmp_path, monkeypatch, flags):
    import uvicorn
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: None)
    result = CliRunner().invoke(cli.app, ["portal", "--data-dir", str(tmp_path), *flags])
    assert result.exit_code != 0
