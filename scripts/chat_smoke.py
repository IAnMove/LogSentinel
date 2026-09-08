"""Browser check: durable chat states, ETA, reload and explicit timeout recovery."""

import asyncio
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
import uvicorn
from playwright.sync_api import sync_playwright
from logsentinel.portal.app import create_app
from logsentinel.portal.analysis import ReviewClient
from logsentinel.portal.models import Machine

with tempfile.TemporaryDirectory(prefix="sentinel-chat-") as directory:
    app = create_app(directory, background=False)
    store = app.state.store
    machine = store.put("machine", Machine(name="Chat test machine").model_dump())
    gate = threading.Event()
    entered = threading.Event()
    fail = False
    calls = []

    async def model(self, payload, **kwargs):
        calls.append(payload)
        entered.set()
        await asyncio.to_thread(gate.wait)
        if fail:
            raise httpx.ReadTimeout("Synthetic model timeout")
        return {
            "answer": "The supplied evidence does not establish a credential leak.",
            "evidence_ids": [],
        }

    original = ReviewClient.call
    ReviewClient.call = model
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    loop = None

    async def serve():
        global loop
        loop = asyncio.get_running_loop()
        await app.state.analyzer.lock.acquire()
        await server.serve()

    thread = threading.Thread(target=lambda: asyncio.run(serve()), daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    errors = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1280, "height": 1050})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}")
            page.get_by_label("Access key").fill(store.meta("admin_token"))
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.get_by_role("button", name="Log assistant", exact=True).click()
            page.get_by_label("Question or filter request").fill(
                "Is this a false positive?"
            )
            page.get_by_role("button", name="Queue question", exact=True).click()
            page.locator('.chat-request-status[data-state="queued"]').wait_for()
            assert not calls
            page.get_by_label("Language / Idioma").select_option("es")
            page.get_by_text(
                "En cola · todavía no se ha enviado al modelo", exact=True
            ).wait_for()
            page.get_by_role(
                "button", name="Cancelar pregunta en cola", exact=True
            ).click()
            page.locator('.chat-request-status[data-state="cancelled"]').wait_for()
            assert not calls
            page.get_by_role(
                "button", name="Reintentar esta pregunta", exact=True
            ).click()
            page.locator('.chat-request-status[data-state="queued"]').wait_for()
            loop.call_soon_threadsafe(app.state.analyzer.lock.release)
            page.locator('.chat-request-status[data-state="running"]').wait_for()
            assert entered.is_set()
            page.reload()
            page.get_by_role("button", name="Asistente", exact=True).click()
            page.locator('.chat-request-status[data-state="running"]').wait_for()
            assert len(calls) == 1
            page.screenshot(path="/tmp/logsentinel-chat-running.png", full_page=True)
            gate.set()
            page.locator('.chat-request-status[data-state="completed"]').wait_for()
            page.get_by_text(
                "The supplied evidence does not establish a credential leak.",
                exact=False,
            ).wait_for()
            fail = True
            page.get_by_label("Pregunta o petición de filtro").fill("A second question")
            page.get_by_role("button", name="Consultar", exact=True).click()
            page.locator('.chat-request-status[data-state="failed"]').wait_for()
            page.get_by_text("Tiempo de espera agotado", exact=True).wait_for()
            assert (
                page.get_by_label("Pregunta o petición de filtro").input_value()
                == "A second question"
            )
            assert len(calls) == 2
            page.get_by_label("Language / Idioma").select_option("en")
            page.get_by_text("Model response timed out", exact=True).wait_for()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            browser.close()
        assert not errors, errors
        print(
            "PASS: queued, cancel, retry, running, reload, completed, timeout, EN/ES, no duplicate calls and mobile"
        )
    finally:
        gate.set()
        server.should_exit = True
        thread.join(timeout=5)
        ReviewClient.call = original
