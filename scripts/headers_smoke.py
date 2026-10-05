"""Real Chromium check that bad JSON in a destination's headers is explained, not leaked.

Before, the browser's own parse error ("Unexpected token ... in JSON at position 3")
reached the screen in English, with no field named. Run after installing optional
playwright and `playwright install chromium`.
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

with tempfile.TemporaryDirectory(prefix="sentinel-headers-") as d:
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
        page.get_by_role("button", name="Notificaciones", exact=True).click()
        page.get_by_role("button", name="Añadir", exact=True).click()
        page.get_by_label("Nombre", exact=True).fill("Webhook de prueba")
        page.locator("select[name='kind']").select_option("webhook")
        group = page.locator("[data-notification-channel='webhook']")
        group.locator("[data-notification-field='url']").fill("https://example.com/hook")
        headers = group.locator("[data-notification-field='headers']")
        notice = page.locator("#notice")

        def save_with(text):
            headers.fill(text)
            page.get_by_role("button", name="Guardar", exact=True).click()
            notice.wait_for()
            return notice.inner_text()

        for bad in ["{no es json", "[1, 2]", '"texto"', "42", "null"]:
            message = save_with(bad)
            assert "objeto JSON válido" in message, (bad, message)
            assert "Unexpected" not in message and "JSON.parse" not in message, message
        assert not app.state.store.objects("destination"), "nothing is saved with bad headers"

        page.get_by_label("Language / Idioma").select_option("en")
        page.wait_for_function("document.querySelector('#nav button') && document.querySelector('#nav').innerText.includes('Notifications')")
        headers = page.locator("[data-notification-channel='webhook'] [data-notification-field='headers']")
        headers.fill("{oops")
        page.get_by_role("button", name="Save", exact=True).click()
        assert "valid JSON object" in notice.inner_text(), notice.inner_text()

        headers.fill('{"X-Token": "valor"}')
        page.get_by_role("button", name="Save", exact=True).click()
        page.get_by_text("Configuration saved.", exact=True).wait_for()
        (saved,) = app.state.store.objects("destination")
        assert saved["kind"] == "webhook" and saved["headers"] == {"X-Token": "valor"}
        assert not errors, errors
        browser.close()
print("PASS: bad headers JSON is explained in both languages and a valid object is saved")
