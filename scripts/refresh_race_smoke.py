"""Real Chromium check that a slow refresh never rebuilds a form someone is typing in.

The page polls the portal state every 15 seconds and redraws the summary. The poll
decides to run before it asks, and on a loaded machine the answer can take seconds.
If the person has opened a form by then, redrawing throws away what they typed.
Run after installing optional playwright and `playwright install chromium`.
"""

import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright
from logsentinel.portal.app import create_app

SLOW = 4000

with tempfile.TemporaryDirectory(prefix="sentinel-race-") as d:
    app = create_app(Path(d) / "data", background=False)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(400):
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise SystemExit("The portal did not start")
    port = server.servers[0].sockets[0].getsockname()[1]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1440, "height": 1000}, locale="es-ES")
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{port}")
        page.get_by_label("Language / Idioma").select_option("es")
        page.get_by_label("Clave de acceso").fill(app.state.store.meta("admin_token"))
        page.get_by_role("button", name="Entrar al portal").click()
        page.get_by_role("button", name="Resumen", exact=True).wait_for()

        # A slow state response, as on a loaded machine.
        page.evaluate(
            """(delay) => { const f = window.fetch; window.fetch = (u, o) =>
                String(u).includes('/api/state') ? new Promise(r => setTimeout(() => r(f(u, o)), delay)) : f(u, o); }""",
            SLOW,
        )
        # A refresh that started on the summary, not awaited so the person keeps going.
        page.evaluate("() => { window.__slow = refresh(); }")
        page.get_by_role("button", name="Máquinas", exact=True).click()
        page.get_by_role("button", name="Añadir", exact=True).click()
        field = page.get_by_label("Nombre", exact=True)
        field.fill("Servidor a medio escribir")
        handle = field.element_handle()
        # The slow answer lands now.
        page.evaluate("() => window.__slow")
        assert handle.evaluate("e => e.isConnected"), "a late refresh rebuilt the form being edited"
        assert page.get_by_label("Nombre", exact=True).input_value() == "Servidor a medio escribir"
        # Once the form is closed the next refresh redraws as usual.
        page.get_by_role("button", name="Cancelar", exact=True).click()
        page.evaluate("() => refresh()")
        page.get_by_role("button", name="Añadir", exact=True).wait_for()
        assert not errors, errors
        browser.close()
print("PASS: a slow refresh does not rebuild a form that was opened while it waited")
