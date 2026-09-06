"""HTTP contract tests using in-process transports; never open sockets."""

import json

import httpx
import pytest

from logsentinel.config import LLMConfig
from logsentinel.llm.client import LLMClient


@pytest.fixture
def capture_http(monkeypatch):
    requests = []

    def handler(request):
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": "synthetic"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}], "message": {"content": "{}"}, "done": True, "done_reason": "stop"})

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    return requests


@pytest.mark.asyncio
@pytest.mark.parametrize("base", ["http://synthetic.invalid", "http://synthetic.invalid/v1", "http://synthetic.invalid/v1/"])
async def test_openai_url_contains_one_version_prefix(capture_http, base):
    client = LLMClient(LLMConfig(provider="openai", base_url=base))
    await client.check_health()
    await client._call_openai("synthetic")
    assert [r.url.path for r in capture_http] == ["/v1/models", "/v1/chat/completions"]


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["ollama", "openai"])
async def test_configured_token_limit_is_honored(capture_http, provider):
    client = LLMClient(LLMConfig(provider=provider, base_url="http://synthetic.invalid", max_tokens=123))
    if provider == "ollama":
        await client._call_ollama("synthetic")
        assert json.loads(capture_http[0].content)["options"]["num_predict"] == 123
    else:
        await client._call_openai("synthetic")
        assert json.loads(capture_http[0].content)["max_tokens"] == 123


@pytest.mark.asyncio
@pytest.mark.parametrize("provider,reason", [("openai", "length"), ("openai", "content_filter"), ("ollama", "length")])
async def test_backend_truncation_cannot_suppress_even_with_complete_json(monkeypatch, provider, reason):
    from logsentinel.core.models import Category, Incident

    raw = json.dumps({"alert_needed": False, "severity": "LOW", "category": "ANOMALY", "title": "Synthetic", "summary": "Synthetic", "confidence": 0.9, "reasoning": None, "matched_memory_rule": None, "suggested_ignore_pattern": None, "recommended_action": None})
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": raw}, "finish_reason": reason}], "message": {"content": raw}, "done": True, "done_reason": reason})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    client = LLMClient(LLMConfig(provider=provider, base_url="http://synthetic.invalid"))
    verdict = await client.analyze(Incident(service="synthetic", signature="synthetic", category_hint=Category.ANOMALY))
    assert verdict.alert_needed is True
