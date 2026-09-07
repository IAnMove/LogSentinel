"""Exercise problem chat and durable investigation in a real browser, with fake LLM."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import socket, tempfile, threading, time
import uvicorn
from playwright.sync_api import sync_playwright
from logsentinel.portal.app import create_app
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.analysis import ReviewClient

with tempfile.TemporaryDirectory(prefix="sentinel-problem-") as directory:
    app = create_app(directory)
    store = app.state.store
    machine = store.put("machine", Machine(name="Test server").model_dump())
    source = store.put(
        "source", Source(name="API", machine_id=machine, kind="push").model_dump()
    )
    store.ingest(
        store.get("source", source),
        [
            {"origin": "1", "message": "request-77 failed", "service": "api"},
            {
                "origin": "2",
                "message": "request-77 upstream timeout",
                "service": "proxy",
            },
        ],
    )
    evidence = store.events()[0]
    problem = app.state.analyzer.save_finding(
        machine,
        dict(
            title="Failed request",
            summary="Original hypothesis",
            severity="HIGH",
            category="reliability",
            evidence_ids=[evidence["id"]],
            reasoning="Inspect the upstream",
            next_steps="Check proxy",
        ),
        [evidence["id"]],
    )
    calls = []

    async def fake(self, payload, **kwargs):
        calls.append(kwargs["kind"])
        if kwargs["kind"] == "research_plan":
            return {"terms": ["request-77"], "services": []}
        return {
            "answer": "Investigate the proxy timeout",
            "evidence_ids": [payload["events"][-1]["id"]],
            "filter": None,
        }

    ReviewClient.call = fake
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
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}")
            page.get_by_label("Language / Idioma").select_option("es")
            page.get_by_label("Clave de acceso").fill(store.meta("admin_token"))
            page.get_by_role("button", name="Entrar al portal").click()
            page.get_by_role("button", name="Problemas", exact=True).click()
            page.get_by_role("button", name="Ver evidencia", exact=True).click()
            page.get_by_role(
                "button", name="Preguntar al asistente", exact=True
            ).click()
            page.locator("#content").get_by_text(
                "Original hypothesis", exact=True
            ).wait_for()
            assert "Failed request" in page.locator("#content textarea").input_value()
            assert calls == []
            page.get_by_role("button", name="Consultar", exact=True).click()
            page.locator(".message").filter(
                has_text="Investigate the proxy timeout"
            ).wait_for()
            assert calls == ["chat"]
            page.locator("#content").get_by_role(
                "button", name="Ver más detalles", exact=True
            ).click()
            page.get_by_role(
                "button", name="Buscar más detalles del problema", exact=True
            ).click()
            page.locator(".message").filter(
                has_text="Investigate the proxy timeout"
            ).wait_for(timeout=15000)
            assert calls == ["chat", "research_plan", "research"]
            page.get_by_label("Language / Idioma").select_option("en")
            page.get_by_role("button", name="Ask the assistant", exact=True).wait_for()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            browser.close()
        assert not errors, errors
        print(
            "PASS: focused problem, exact context preview, cited chat, persistent deeper search, EN/ES and mobile"
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)
