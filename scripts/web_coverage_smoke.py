"""Real Chromium check that a healthy web source does not look like a coverage gap.

Access-log requests are always left to the detectors, so a source made of them
is 100% "not sent to the model" by design. The coverage screens used to list that
as lines "left out by source selection", in warning style. Run after installing
optional playwright and `playwright install chromium`.
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
from logsentinel.portal.collect import normalize
from logsentinel.portal.models import Machine, Source

LINE = '192.0.2.{ip} - - [10/Oct/2026:13:{minute:02d}:{second:02d} +0000] "GET /index.html HTTP/1.1" 200 512 "-" "Mozilla/5.0"'

with tempfile.TemporaryDirectory(prefix="sentinel-webcov-") as d:
    app = create_app(Path(d) / "data", background=False)
    store = app.state.store
    machine = store.put("machine", Machine(name="Servidor web").model_dump())
    sid = store.put("source", Source(name="nginx", machine_id=machine, kind="push", enabled=True).model_dump())
    lines = [LINE.format(ip=n % 200 + 1, minute=n // 60 % 60, second=n % 60) for n in range(120)]
    store.ingest(store.get("source", sid), [normalize(text, "remote", f"w{i}") for i, text in enumerate(lines)])
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
        page.get_by_label("Clave de acceso").fill(store.meta("admin_token"))
        page.get_by_role("button", name="Entrar al portal").click()
        page.get_by_role("button", name="Resumen", exact=True).click()

        expected = "120 peticiones web: las vigilan los detectores"
        page.get_by_text(expected, exact=False).first.wait_for(state="attached")
        monitor = page.locator("#monitor-status")
        assert "por selección de fuente" not in monitor.inner_text(), monitor.inner_text()
        assert page.locator(".monitor-warning").filter(has_text="Sin analizar fuera de la cola").count() == 0

        page.get_by_role("button", name="Cobertura y capacidad", exact=True).click()
        content = page.locator("#content")
        content.get_by_text("peticiones web: las vigilan los detectores", exact=False).first.wait_for()
        assert "apartados por filtros o selección" not in page.locator("#content").inner_text()

        page.get_by_label("Language / Idioma").select_option("en")
        content.get_by_text("web requests: the detectors watch them", exact=False).first.wait_for()
        assert not errors, errors
        browser.close()
print("PASS: web requests are shown as expected, apart from real selection gaps, in both screens and languages")
