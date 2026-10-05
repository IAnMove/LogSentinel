"""Real Chromium checks of the 15-second poll: a failing poll is announced once, and a
slow refresh never rebuilds a form someone is typing in.

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

        # A new installation opens on the setup wizard; the poll runs on the summary.
        page.get_by_role("button", name="Resumen", exact=True).click()
        page.wait_for_function("view === 'summary'")

        # A poll that keeps failing is announced once. #notice is a live region, and
        # writing the same text into it again makes a screen reader read it again.
        page.evaluate(
            """() => { window.__announced = 0;
                new MutationObserver(() => window.__announced++).observe(
                  document.querySelector('#notice'), {childList: true, characterData: true, subtree: true}); }"""
        )
        page.route("**/api/state", lambda route: route.abort())
        for _ in range(3):
            # Becoming visible again runs the poll at once instead of in 15 seconds.
            page.evaluate("() => document.dispatchEvent(new Event('visibilitychange'))")
            page.wait_for_timeout(500)
        page.unroute("**/api/state")
        announced = page.evaluate("window.__announced")
        assert page.locator("#notice.error").is_visible(), "the failure is shown"
        assert announced == 1, f"the same poll failure was announced {announced} times"

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
print("PASS: a failing poll is announced once; a slow refresh does not rebuild a form opened while it waited")
