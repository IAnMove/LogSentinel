import hashlib
import json
import pytest
from fastapi.testclient import TestClient
from logsentinel.portal.app import create_app
from logsentinel.portal.analysis import ReviewClient


@pytest.fixture
def client(tmp_path):
    app = create_app(tmp_path, background=False)
    with TestClient(app, base_url="http://localhost") as c:
        assert (
            c.post(
                "/login", json={"token": app.state.store.meta("admin_token")}
            ).status_code
            == 200
        )
        c.headers["X-LogSentinel"] = "portal"
        yield c, app.state.store


def machine_source(c):
    m = c.post("/api/objects/machine", json={"name": "A"}).json()["id"]
    r = c.post(
        "/api/objects/source",
        json={"name": "remote", "machine_id": m, "kind": "push", "enabled": True},
    )
    assert r.status_code == 200, r.text
    return m, r.json()["id"]


def test_auth_csrf_and_host_are_required(tmp_path):
    app = create_app(tmp_path, background=False)
    with TestClient(app, base_url="http://localhost") as c:
        assert c.get("/api/state").status_code == 401
        assert c.post("/login", json={"token": "wrong"}).status_code == 401
        c.post("/login", json={"token": app.state.store.meta("admin_token")})
        assert c.post("/api/objects/machine", json={"name": "A"}).status_code == 403
        assert c.get("/", headers={"host": "attacker.example"}).status_code == 400
        assert (
            c.post(
                "/api/logout",
                headers={
                    "X-LogSentinel": "portal",
                    "Origin": "http://attacker.example",
                },
            ).status_code
            == 403
        )


def test_destinations_write_only_secrets_and_save_does_not_send(client):
    c, s = client
    body = {
        "name": "t",
        "kind": "telegram",
        "token": "synthetic-secret",
        "chat_id": "42",
        "enabled": True,
    }
    result = c.post("/api/objects/destination", json=body)
    assert result.status_code == 200, result.text
    assert "synthetic-secret" not in result.text
    id = result.json()["id"]
    body = result.json()
    body["name"] = "renamed"
    assert c.post("/api/objects/destination", json=body).status_code == 200
    assert s.get("destination", id)["token"] == "synthetic-secret"
    assert "synthetic-secret" not in c.get("/api/state").text
    assert s.rows("deliveries") == []


def test_push_auth_machine_binding_and_replay(client):
    c, s = client
    m, source = machine_source(c)
    token = c.post("/api/sources/" + source + "/token").json()["token"]
    body = {
        "events": [
            {"id": "sender-1", "raw": "2026-01-01T00:00:00Z forged sshd: hello"}
        ],
        "machine_id": "forged",
    }
    assert c.post("/ingest/" + source, json=body).status_code == 401
    headers = {"Authorization": "Bearer " + token}
    result = c.post("/ingest/" + source, json=body, headers=headers)
    assert result.status_code == 200, result.text
    assert result.json()["accepted"] == 1
    assert (
        c.post("/ingest/" + source, json=body, headers=headers).json()["accepted"] == 0
    )
    assert s.events()[0]["machine_id"] == m
    c.post("/api/sources/" + source + "/token")
    assert c.post("/ingest/" + source, json=body, headers=headers).status_code == 401


def test_disabled_destination_cancels_queue(client):
    c, s = client
    d = c.post(
        "/api/objects/destination",
        json={"name": "file", "kind": "file", "enabled": True},
    ).json()
    from logsentinel.portal.store import dumps

    with s.connect() as db:
        db.execute(
            "INSERT INTO deliveries VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("q", d["id"], "p", "{}", "pending", 0, 0, 0, 0, None),
        )
    d["enabled"] = False
    assert c.post("/api/objects/destination", json=d).status_code == 200
    assert s.rows("deliveries")[0]["status"] == "cancelled"


def test_regex_preview_does_not_save_rule(client):
    c, s = client
    m, source = machine_source(c)
    s.ingest(
        {"id": source, "machine_id": m},
        [
            {"origin": "1", "message": "192.0.2.1 problem"},
            {"origin": "2", "message": "192.0.2.10 problem"},
        ],
    )
    r = c.post(
        "/api/rules/preview",
        json={
            "name": "specific IP",
            "kind": "ip",
            "pattern": "192.0.2.1",
            "machine_id": m,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["matched"] == 1
    assert s.objects("rule") == []


def test_chat_proposal_is_not_automatically_applied(client, monkeypatch):
    c, s = client
    m, source = machine_source(c)

    async def fake(*args, **kwargs):
        return {
            "answer": "Revisa este filtro",
            "evidence_ids": [],
            "filter": {
                "name": "proposal",
                "kind": "regex",
                "action": "exclude",
                "pattern": "foo",
            },
        }

    monkeypatch.setattr(ReviewClient, "call", fake)
    r = c.post("/api/chat", json={"message": "make filter", "machine_id": m})
    assert r.status_code == 200, r.text
    assert r.json()["filter"]["machine_id"] == m
    assert s.objects("rule") == []


def test_model_and_context_validation(client):
    c, s = client
    assert (
        c.post(
            "/api/settings", json={"context_tokens": 2048, "input_budget": 5000}
        ).status_code
        == 422
    )
    assert (
        c.post(
            "/api/settings", json={"llm": {"base_url": "file:///etc/passwd"}}
        ).status_code
        == 422
    )


def test_history_search_reaches_beyond_first_page(client):
    c, s = client
    m, source = machine_source(c)
    obj = s.get("source", source)
    s.ingest(
        obj,
        [
            {
                "origin": str(i),
                "message": "needle" if i == 220 else "ordinary",
                "service": "test",
            }
            for i in range(250)
        ],
    )
    r = c.get("/api/events", params={"machine_id": m, "q": "needle"}).json()
    assert [e["message"] for e in r["events"]] == ["needle"]
    assert r["scanned"] == 250
    assert r["exhausted"] is True
    assert r["next_offset"] == 250


def test_model_metadata_suggestion_uses_server_information(client, monkeypatch):
    import httpx

    c, s = client
    model = s.settings().llm.model

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": model}]})
        if request.url.path == "/api/show":
            return httpx.Response(
                200, json={"model_info": {"test.context_length": 4096}}
            )
        return httpx.Response(
            200, json={"models": [{"name": model, "context_length": 2048}]}
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    before = s.settings().model_dump()
    result = c.post("/api/model/info").json()
    assert result["reported_maximum"] == 4096
    assert result["running_context"] == 2048
    assert result["suggested_context"] == 2048
    assert result["suggested_input_budget"] == 0
    assert s.settings().model_dump() == before
