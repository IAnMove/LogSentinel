"""Browser provider presets, draft discovery/test, secrets, EN/ES and mobile."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import socket
import tempfile
import threading
import time

import httpx
import uvicorn
from playwright.sync_api import sync_playwright
from logsentinel.portal.app import create_app
from logsentinel.portal.models import Machine


seen = []


def model(request):
    seen.append(request)
    if request.url.path == "/api/tags":
        return httpx.Response(200, json={"models": [{"name": "qwen-test:8b"}]})
    if request.url.path == "/api/show":
        return httpx.Response(404, json={"error": "not installed"})
    if request.url.path == "/api/ps":
        return httpx.Response(200, json={"models": []})
    return httpx.Response(
        200,
        json={
            "message": {"content": '{"findings":[]}'},
            "done": True,
            "prompt_eval_count": 20,
            "eval_count": 5,
        },
    )


original = httpx.AsyncClient
httpx.AsyncClient = lambda **kwargs: original(
    transport=httpx.MockTransport(model), **kwargs
)
with tempfile.TemporaryDirectory(prefix="sentinel-providers-") as directory:
    app = create_app(directory, background=False)
    store = app.state.store
    store.put("machine", Machine(name="Test machine", kind="local").model_dump())
    cfg = store.settings()
    cfg.llm.provider = "openai"
    cfg.llm.base_url = "http://127.0.0.1:8081/v1"
    cfg.llm.api_key = "synthetic-private-key"
    cfg.llm.enable_thinking = False
    store.set_meta("settings", cfg.model_dump_json())
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    errors = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}")
            page.get_by_label("Access key").fill(store.meta("admin_token"))
            page.get_by_role("button", name="Sign in").click()
            page.locator("#nav").get_by_role(
                "button", name="Setup wizard", exact=True
            ).click()
            page.get_by_label("LLM server", exact=True).wait_for()
            assert (
                page.evaluate(
                    "llmFormSettings(document.querySelector('#content form'), S.settings).llm.enable_thinking"
                )
                is False
            )
            page.get_by_role("button", name="Model and analysis", exact=True).click()
            assert "8081/v1" in page.locator(".provider-active").inner_text()
            for preset in [
                "llama_cpp",
                "lm_studio",
                "vllm",
                "litellm",
                "balancer",
                "ollama",
            ]:
                page.get_by_label("LLM server", exact=True).select_option(preset)
                assert page.get_by_label("API protocol").input_value() == (
                    "ollama" if preset == "ollama" else "openai"
                )
                assert page.locator('[name="enable_thinking"]').input_value() == "auto"
            page.get_by_role("button", name="Find models on this server").click()
            page.get_by_role("button", name="qwen-test:8b", exact=True).click()
            page.get_by_role(
                "button", name="Test these settings without saving"
            ).click()
            page.get_by_text("Connection verified", exact=True).wait_for()
            assert store.settings().llm.base_url == cfg.llm.base_url
            assert store.settings().llm.api_key == "synthetic-private-key"
            assert all("authorization" not in req.headers for req in seen)
            assert "synthetic-private-key" not in page.locator("body").inner_text()
            assert json.loads(seen[-1].content)["model"] == "qwen-test:8b"
            page.get_by_role("button", name="Save settings", exact=True).click()
            page.get_by_text("Settings applied.", exact=True).wait_for()
            assert store.settings().llm.provider == "ollama"
            assert store.settings().llm.api_key is None
            page.get_by_label("Language / Idioma").select_option("es")
            page.get_by_label("Servidor LLM", exact=True).wait_for()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path="/tmp/logsentinel-providers.png", full_page=True)
            browser.close()
        assert not errors, errors
        print(
            "PASS: six provider presets, draft discovery/test, unchanged active settings, credential isolation, EN/ES and mobile"
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        httpx.AsyncClient = original
