"""Browser regression: fresh ES/EN setup, private help and unattended analysis.

Uses temporary logs, a stubbed model and real background workers; no external
service or real notification is contacted.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import socket
import tempfile
import threading
import time
import uvicorn
from playwright.sync_api import sync_playwright
from logsentinel.portal.app import create_app
from logsentinel.portal.analysis import ReviewClient


def wait_until(check, seconds=15):
    deadline = time.monotonic() + seconds
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError("Timed out waiting for automatic monitoring")
        time.sleep(0.1)


with tempfile.TemporaryDirectory(prefix="sentinel-setup-") as tmp:
    directory = Path(tmp)
    logs = directory / "app.log"
    logs.write_text("2026-09-07T12:00:00Z demo app: ERROR connection pool exhausted\n")
    calls = []

    async def stub(self, payload, **kw):
        calls.append((payload, kw))
        if kw.get("kind") == "help":
            return {"answer": "Journal needs no path. <script>invalid()</script>"}
        events = payload.get("groups", payload.get("events", []))
        if not events:
            return {"findings": []}
        return {
            "findings": [
                {
                    "title": "Connection failure",
                    "summary": "Check connections",
                    "severity": "HIGH",
                    "category": "reliability",
                    "evidence_ids": [events[0]["id"]],
                    "next_steps": ["Check active connections"],
                }
            ]
        }

    original = ReviewClient.call
    ReviewClient.call = stub
    app = create_app(directory / "data")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    wait_until(lambda: server.started)
    errors = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(
                viewport={"width": 1440, "height": 1050}, locale="en-US"
            )
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}")
            page.get_by_label("Access key", exact=True).fill(
                app.state.store.meta("admin_token")
            )
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.get_by_role("heading", name="Connect the LLM", exact=True).wait_for()
            page.get_by_label("Model", exact=True).fill("test-model")
            page.get_by_label("API key (blank keeps saved value)").fill("private-key")
            page.get_by_label("Language / Idioma").select_option("es")
            page.get_by_role("heading", name="Conectar el LLM", exact=True).wait_for()
            assert page.get_by_label("Modelo", exact=True).input_value() == "test-model"
            assert (
                page.get_by_label("Clave API (vacío conserva)").input_value()
                == "private-key"
            )
            page.get_by_label("Language / Idioma").select_option("en")
            page.get_by_role(
                "button", name="Save, test and continue", exact=True
            ).click()
            page.get_by_role("heading", name="Choose a machine", exact=True).wait_for()
            page.get_by_label("Name", exact=True).fill("Resumen")
            page.get_by_role("button", name="Save and continue", exact=True).click()
            page.get_by_role("heading", name="Connect logs", exact=True).wait_for()
            page.get_by_label("Source type").select_option("file")
            page.get_by_label("Path (file or folder)").fill(str(logs))
            page.get_by_label("Import existing history on first read").check()
            page.get_by_role(
                "button", name="Enable source and test reading", exact=True
            ).click()
            page.get_by_role("heading", name="Enable and learn", exact=True).wait_for()
            page.get_by_label("Interval between cycles (seconds)").fill("5")
            page.screenshot(path="/tmp/logsentinel-setup.png", full_page=True)
            page.get_by_role(
                "button", name="Finish and enable automatic analysis", exact=True
            ).click()
            page.get_by_role("heading", name="Overview", exact=True).wait_for()
            wait_until(lambda: len(app.state.store.rows("jobs")) >= 1)
            with logs.open("a") as f:
                f.write("2026-09-07T12:00:10Z demo app: ERROR another failure\n")
            wait_until(
                lambda: len(app.state.store.rows("jobs")) >= 2
                and all(j["status"] == "done" for j in app.state.store.rows("jobs"))
            )
            assert all(j["status"] == "done" for j in app.state.store.rows("jobs"))
            page.get_by_text("Continuous capture active", exact=True).wait_for()
            assert app.state.store.settings().enabled
            assert len(app.state.store.objects("source")) == 1
            assert len(app.state.store.objects("machine")) == 1
            page.get_by_role("button", name="Machines", exact=True).click()
            page.get_by_role("cell", name="Resumen", exact=True).wait_for()
            page.get_by_role("button", name="Ask the LLM", exact=True).click()
            page.get_by_label("Your question", exact=True).fill(
                "How does journal capture work?"
            )
            page.locator("#help-send").click()
            page.locator("#help-conversation").get_by_text(
                "Journal needs no path.", exact=False
            ).wait_for()
            help_payload = [p for p, kw in calls if kw.get("kind") == "help"][0]
            assert "events" not in help_payload and "private-key" not in str(
                help_payload
            )
            page.locator("#help-close").click()
            page.get_by_label("Language / Idioma").select_option("es")
            page.get_by_role("heading", name="Máquinas", exact=True).wait_for()
            page.reload()
            page.get_by_role("button", name="Resumen", exact=True).wait_for()
            page.get_by_text("Captura continua activa", exact=True).wait_for()
            page.screenshot(path="/tmp/logsentinel-monitor.png", full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            browser.close()
        assert not errors, errors
        print(
            "PASS: English/Spanish setup, preserved form edits and log names, model test, private help, continuous capture, two automatic cycles, persisted language and mobile layout"
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        ReviewClient.call = original
