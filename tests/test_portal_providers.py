"""Provider switching, draft diagnostics and credential isolation over real transports."""

import json

import httpx
import pytest

from test_portal_api import client


@pytest.fixture
def transport(monkeypatch):
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "installed:8b"}]})
        if request.url.path == "/api/show":
            return httpx.Response(404, json={"error": "model not found"})
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": []})
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "balanced-alias"}]})
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"findings":[]}'}, "finish_reason": "stop"}
                ],
                "message": {"content": '{"findings":[]}'},
                "done": True,
                "prompt_eval_count": 12,
                "eval_count": 5,
                "usage": {"prompt_tokens": 12, "completion_tokens": 5},
            },
        )

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.MockTransport(handle), **kwargs),
    )
    return seen


@pytest.mark.parametrize(
    "server",
    ["ollama", "llama_cpp", "lm_studio", "vllm", "litellm", "balancer", "custom"],
)
def test_draft_provider_test_uses_candidate_without_changing_active_config(
    client, transport, server
):
    c, s = client
    c.post("/api/settings", json={"llm": {"api_key": "old-server-secret"}})
    assert c.post("/api/model/test").status_code == 200
    verified = s.meta("model_test")
    before = s.settings().model_dump()
    draft = {
        "llm": {
            "provider": "ollama" if server == "ollama" else "openai",
            "server_type": server,
            "base_url": "http://127.0.0.1:9999",
            "model": "balanced-alias",
            "api_key": "",
            "enable_thinking": False if server == "ollama" else None,
        }
    }
    result = c.post("/api/model/test", json=draft)
    assert result.status_code == 200, result.text
    assert not result.json()["saved_config"]
    assert result.json()["model"] == "balanced-alias"
    assert result.json()["input_tokens"] == 12
    assert "old-server-secret" not in result.text
    request = transport[-1]
    assert "authorization" not in request.headers
    body = json.loads(request.content)
    assert body["model"] == "balanced-alias"
    if server == "ollama":
        assert request.url.path == "/api/chat"
        assert body["think"] is False and body["format"] == "json"
        assert body["options"]["num_ctx"] == before["context_tokens"]
    else:
        assert request.url.path == "/v1/chat/completions"
        assert body["response_format"] == {"type": "json_object"}
        assert "chat_template_kwargs" not in body
    assert s.settings().model_dump() == before
    assert s.meta("model_test") == verified
    assert c.get("/api/state").json()["setup"]["model_tested"]


def test_keys_are_retained_only_for_the_same_endpoint_and_can_be_cleared(
    client, transport
):
    c, s = client
    assert (
        c.post("/api/settings", json={"llm": {"api_key": "old-secret"}}).status_code
        == 200
    )
    c.post("/api/settings", json={"llm": {"api_key": "", "model": "another"}})
    assert s.settings().llm.api_key == "old-secret"
    c.post("/api/model/info", json={"llm": {"base_url": "http://localhost:9999"}})
    assert all("authorization" not in request.headers for request in transport)
    c.post("/api/settings", json={"llm": {"base_url": "http://localhost:9999"}})
    assert s.settings().llm.api_key is None
    c.post("/api/settings", json={"llm": {"api_key": "new-secret"}})
    c.post("/api/settings", json={"clear_api_key": True})
    assert s.settings().llm.api_key is None


def test_discovery_allows_missing_ollama_model_and_remote_consent_is_enforced(
    client, transport
):
    c, s = client
    result = c.post("/api/model/info")
    assert result.status_code == 200
    assert result.json()["models"] == ["installed:8b"]
    before = len(transport)
    draft = {"llm": {"base_url": "https://remote.invalid", "api_key": "draft-secret"}}
    assert c.post("/api/model/info", json=draft).status_code == 400
    assert c.post("/api/model/test", json=draft).status_code == 502
    assert len(transport) == before


@pytest.mark.parametrize(
    "provider,path,models",
    [
        ("ollama", "/api/tags", ["installed:8b"]),
        ("openai", "/v1/models", ["balanced-alias"]),
    ],
)
def test_model_list_needs_no_model_metadata_or_inference(
    client, transport, provider, path, models
):
    c, s = client
    before = s.settings().model_dump()
    response = c.post(
        "/api/model/info?models_only=true",
        json={"llm": {"provider": provider, "model": "/old/server/model.gguf"}},
    )
    assert response.status_code == 200
    assert response.json()["models"] == models
    assert [r.url.path for r in transport] == [path]
    assert transport[0].method == "GET"
    assert s.settings().model_dump() == before


@pytest.mark.parametrize(
    "provider,key,collection", [("ollama", "name", "models"), ("openai", "id", "data")]
)
def test_model_list_discards_invalid_and_duplicate_names(
    client, monkeypatch, provider, key, collection
):
    c, s = client
    original = httpx.AsyncClient
    body = {
        collection: [
            {key: value} for value in ("second", None, "", "first", "second", 42, " ")
        ]
    }
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
            **kwargs,
        ),
    )
    response = c.post(
        "/api/model/info?models_only=true", json={"llm": {"provider": provider}}
    )
    assert response.status_code == 200
    assert response.json()["models"] == ["first", "second"]


def test_html_frontend_is_not_mistaken_for_a_model_server(client, monkeypatch):
    c, s = client
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(
                lambda r: httpx.Response(200, text="<!doctype html>BigPAPI")
            ),
            **kwargs,
        ),
    )
    assert c.post("/api/model/info").status_code == 502
    assert c.post("/api/model/test").status_code == 502


@pytest.mark.parametrize(
    "body", [{"choices": []}, {"choices": [{"message": {"content": None}}]}, []]
)
def test_malformed_provider_shapes_return_a_diagnostic_error(client, monkeypatch, body):
    c, s = client
    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: original(
            transport=httpx.MockTransport(lambda r: httpx.Response(200, json=body)),
            **kwargs,
        ),
    )
    response = c.post("/api/model/test", json={"llm": {"provider": "openai"}})
    assert response.status_code == 502
    assert "Model test failed" in response.json()["detail"]
