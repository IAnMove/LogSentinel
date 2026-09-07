import hashlib
from test_portal_api import client, machine_source


def test_widget_key_is_revocable_and_cannot_access_logs_settings_or_login(client):
    c, store = client
    machine, source = machine_source(c)
    store.ingest(
        store.get("source", source),
        [{"origin": "secret", "message": "PRIVATE-EVIDENCE"}],
    )
    assert c.get("/widget/status").status_code == 401
    admin = store.meta("admin_token")
    assert (
        c.get(
            "/widget/status", headers={"Authorization": "Bearer " + admin}
        ).status_code
        == 401
    )
    token = c.post("/api/widget/token").json()["token"]
    assert store.meta("widget_token") == hashlib.sha256(token.encode()).hexdigest()
    headers = {"Authorization": "Bearer " + token}
    c.cookies.clear()
    response = c.get("/widget/status", headers=headers)
    assert response.status_code == 200
    assert response.json()["machines"][0]["id"] == machine
    assert "PRIVATE-EVIDENCE" not in response.text
    assert token not in response.text and admin not in response.text
    assert c.get("/api/state", headers=headers).status_code == 401
    assert c.post("/login", json={"token": token}).status_code == 401
    assert c.post("/api/scan", headers=headers).status_code == 401
    assert (
        c.get("/widget/status", headers=dict(headers, Host="evil.example")).status_code
        == 400
    )
    c.post("/login", json={"token": admin})
    c.post("/api/widget/token")
    assert c.get("/widget/status", headers=headers).status_code == 401
    new = c.post("/api/widget/token").json()["token"]
    c.delete("/api/widget/token")
    assert (
        c.get("/widget/status", headers={"Authorization": "Bearer " + new}).status_code
        == 401
    )
