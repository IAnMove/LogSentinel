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
    if request.url.path == "/v1/models":
        return httpx.Response(200, json={"data": [{"id": "balanced-alias"}]})
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
            page.get_by_role("button", name="Refresh models", exact=True).click()
            page.get_by_label("Model", exact=True).select_option(label="balanced-alias")
            assert page.locator('input[name="model"]').input_value() == "balanced-alias"
            assert not page.locator('input[name="model"]').is_visible()
            # Discovery does not depend on partially edited context/output budgets.
            page.get_by_label("Configured effective context").fill("1")
            page.get_by_role("button", name="Refresh models", exact=True).click()
            page.get_by_label("Model", exact=True).select_option(label="balanced-alias")
            page.get_by_label("Configured effective context").fill("8192")
            page.get_by_label("Model", exact=True).select_option("manual")
            page.get_by_label("Model ID (manual)", exact=True).fill("manual-route")
            assert store.settings().llm.model == cfg.llm.model
            seen.clear()
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
            # The Ollama list refreshes automatically after a preset change.
            page.get_by_label("Model", exact=True).select_option(label="qwen-test:8b")
            assert not any(req.url.path in ("/api/show", "/api/ps") for req in seen)
            assert not page.locator('input[name="model"]').is_visible()
            # Language changes preserve the chosen model and regenerate its list.
            page.get_by_label("Language / Idioma").select_option("es")
            page.get_by_label("Modelo", exact=True).select_option(label="qwen-test:8b")
            assert page.locator('input[name="model"]').input_value() == "qwen-test:8b"
            page.get_by_label("Language / Idioma").select_option("en")
            page.get_by_label("Model", exact=True).select_option(label="qwen-test:8b")
            # A late response from a previous server cannot replace the new list.
            delayed = []

            def hold_old_server(route):
                if route.request.post_data_json["llm"]["base_url"].endswith(":9988"):
                    delayed.append(route)
                else:
                    route.continue_()

            listing = "**/api/model/info?models_only=true"
            page.route(listing, hold_old_server)
            page.get_by_label("Server URL", exact=True).fill("http://127.0.0.1:9988")
            page.wait_for_timeout(800)
            assert delayed
            page.get_by_label("Server URL", exact=True).fill("http://127.0.0.1:11434")
            page.get_by_label("Model", exact=True).select_option(label="qwen-test:8b")
            for route in delayed:
                route.fulfill(status=200, json={"models": ["old-server-model"]})
            page.wait_for_timeout(100)
            assert page.get_by_label("Model", exact=True).locator(
                "option"
            ).all_text_contents() == ["Enter model ID manually…", "qwen-test:8b"]
            page.unroute(listing)
            # Empty and failed discovery retain the value and manual entry.
            page.route(
                listing, lambda route: route.fulfill(status=200, json={"models": []})
            )
            page.get_by_role("button", name="Refresh models", exact=True).click()
            page.get_by_text(
                "The server publishes no models. You can enter the ID manually.",
                exact=True,
            ).wait_for()
            assert (
                page.get_by_label("Model ID (manual)", exact=True).input_value()
                == "qwen-test:8b"
            )
            page.unroute(listing)
            page.route(
                listing,
                lambda route: route.fulfill(
                    status=503, json={"detail": "synthetic unavailable"}
                ),
            )
            page.get_by_role("button", name="Refresh models", exact=True).click()
            page.get_by_text("Could not load the list.", exact=False).wait_for()
            page.get_by_label("Model ID (manual)", exact=True).fill("manual-alias")
            page.unroute(listing)
            page.get_by_role("button", name="Refresh models", exact=True).click()
            page.get_by_label("Model", exact=True).select_option(label="qwen-test:8b")
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
            "PASS: native model dropdown, automatic Ollama/compatible discovery, manual aliases, draft test, credential isolation, EN/ES and mobile"
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        httpx.AsyncClient = original
