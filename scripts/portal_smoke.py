"""Real Chromium smoke test against temporary data and a stubbed model.
Run after installing optional playwright and `playwright install chromium`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import socket, tempfile, threading, time
import uvicorn
from playwright.sync_api import sync_playwright
from logsentinel.portal.app import create_app

with tempfile.TemporaryDirectory(prefix="sentinel-browser-") as d:
    base = Path(d)
    source = base / "app.log"
    source.write_text("2026-09-06T12:00:00Z demo app: connection pool exhausted\n")
    app = create_app(base / "data", background=False)

    async def model(payload, **kwargs):
        e = payload.get("groups", payload.get("events", []))[0]
        return {
            "findings": [
                {
                    "title": "Pool de conexiones agotado",
                    "summary": "La aplicación no dispone de conexiones.",
                    "severity": "HIGH",
                    "category": "reliability",
                    "evidence_ids": [e["id"]],
                    "reasoning": "Evidencia sintética de prueba.",
                    "next_steps": "Comprobar conexiones activas.",
                }
            ]
        }

    app.state.analyzer.client.call = model
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    errors = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(
                viewport={"width": 1440, "height": 1000}, locale="es-ES"
            )
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}")
            page.get_by_label("Language / Idioma").select_option("es")
            page.get_by_label("Clave de acceso").fill(
                app.state.store.meta("admin_token")
            )
            page.get_by_role("button", name="Entrar al portal").click()
            page.get_by_role("button", name="Máquinas", exact=True).click()
            page.get_by_role("button", name="Añadir", exact=True).click()
            page.get_by_label("Nombre", exact=True).fill("Servidor de prueba")
            page.get_by_role("button", name="Guardar", exact=True).click()
            page.get_by_text("Configuración guardada.", exact=True).wait_for()
            page.get_by_role("button", name="Fuentes", exact=True).click()
            page.get_by_role("button", name="Añadir", exact=True).click()
            page.get_by_label("Nombre", exact=True).fill("Aplicación")
            machine = app.state.store.objects("machine")[0]["id"]
            page.get_by_label("Máquina", exact=True).select_option(machine)
            page.get_by_label("Ruta (archivo o carpeta)", exact=True).fill(str(source))
            page.get_by_label("Importar histórico al iniciar").check()
            page.get_by_role("button", name="Guardar", exact=True).click()
            page.get_by_text("Configuración guardada.", exact=True).wait_for()
            page.get_by_role("button", name="Leer ahora", exact=True).click()
            page.get_by_text("1 eventos nuevos.", exact=False).wait_for()
            page.get_by_role("button", name="Resumen", exact=True).click()
            page.get_by_role("button", name="Analizar ahora").click()
            page.get_by_text("Ciclo terminado:", exact=False).wait_for()
            page.get_by_role("button", name="Problemas", exact=True).click()
            page.get_by_role("button", name="Ver evidencia").click()
            page.get_by_text("Pool de conexiones agotado", exact=True).last.wait_for()
            page.get_by_role(
                "button", name="No notificar este problema", exact=True
            ).click()
            page.get_by_role("button", name="Guardar", exact=True).click()
            page.get_by_text("Configuración guardada.", exact=True).wait_for()
            page.get_by_role("button", name="Notificaciones", exact=True).click()
            page.get_by_role("button", name="Añadir", exact=True).click()
            page.get_by_label("Nombre", exact=True).fill("Archivo de prueba")
            # Guides must follow unsaved selections without changing credentials
            # or sending anything. All notification data here is synthetic.
            requests = []
            page.on(
                "request",
                lambda request: (
                    requests.append(request) if request.method != "GET" else None
                ),
            )
            draft = {
                "url": "https://synthetic.invalid/draft-webhook",
                "token": "synthetic-draft-token",
                "secret": "synthetic-draft-secret",
                "headers": '{"X-Test": "synthetic-draft-header"}',
                "chat_id": "-1234",
            }
            for name, value in draft.items():
                page.locator(f"[name='{name}']").fill(value)
            guide = page.locator(".notification-howto")
            for locale, prefix in [("en", "How to add"), ("es", "Cómo añadir")]:
                page.get_by_label("Language / Idioma").select_option(locale)
                page.wait_for_function(
                    "prefix => document.querySelector('.notification-howto summary').textContent.startsWith(prefix)",
                    arg=prefix,
                )
                for channel in [
                    "system",
                    "telegram",
                    "slack",
                    "discord",
                    "hermes",
                    "n8n",
                    "webhook",
                    "file",
                ]:
                    page.locator("select[name='kind']").select_option(channel)
                    assert guide.get_attribute("data-channel") == channel
                    assert guide.locator("summary").inner_text().startswith(prefix)
                    assert guide.locator("li").count() >= 3
                    assert guide.locator("button").count() == (
                        1 if channel in ("hermes", "n8n") else 0
                    )
                    for name, value in draft.items():
                        assert page.locator(f"[name='{name}']").input_value() == value
                        assert value not in guide.inner_text()
                    for link in guide.locator("a").all():
                        assert link.get_attribute("rel") == "noopener noreferrer"
                        assert "synthetic" not in link.get_attribute("href")
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    ), channel
                    page.set_viewport_size({"width": 1440, "height": 1000})

            # Restoring the draft after a language switch must also update help;
            # the unsaved selection differs from the default Telegram channel.
            page.locator("select[name='kind']").select_option("n8n")
            page.get_by_label("Language / Idioma").select_option("en")
            page.get_by_text("How to add n8n", exact=True).wait_for()
            assert page.locator("select[name='kind']").input_value() == "n8n"
            page.get_by_role("button", name="n8n template", exact=True).click()
            page.locator("#modal[open]").wait_for()
            assert "Configure destination" in page.locator("#modal").inner_text()
            page.locator("#close-modal").click()
            for theme in ["classic", "paper", "tokyo", "gruvbox", "rose"]:
                page.get_by_label("Theme / Tema").select_option(theme)
                assert guide.get_attribute("data-channel") == "n8n"
                assert page.locator("[name='token']").input_value() == draft["token"]
            guide.locator("summary").focus()
            page.keyboard.press("Enter")
            assert not guide.evaluate("node => node.open")
            page.keyboard.press("Enter")
            assert guide.evaluate("node => node.open")
            page.get_by_label("Language / Idioma").select_option("es")
            page.get_by_text("Cómo añadir n8n", exact=True).wait_for()
            assert not requests, [(r.method, r.url) for r in requests]
            for name in draft:
                page.locator(f"[name='{name}']").fill("")
            page.get_by_label("Canal", exact=True).select_option("file")
            page.get_by_role("button", name="Guardar", exact=True).click()
            page.get_by_text("Configuración guardada.", exact=True).wait_for()
            page.get_by_role("button", name="Enviar prueba", exact=True).click()
            page.get_by_text("delivered", exact=True).wait_for()
            page.get_by_role("button", name="Editar", exact=True).click()
            page.get_by_text("Cómo añadir un archivo local", exact=True).wait_for()
            page.get_by_role("button", name="Resumen", exact=True).click()
            page.screenshot(path="/tmp/logsentinel-portal.png", full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate(
                "document.documentElement.scrollWidth <= window.innerWidth"
            )
            browser.close()
        assert not errors, errors
        assert len(app.state.store.objects("rule")) == 1
        assert len(app.state.store.rows("problems")) == 1
        print(
            "PASS: login, machine, import, analysis, evidence, mute, 8 notification guides, draft/language/theme preservation, templates, file delivery, edit and mobile layout"
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)
