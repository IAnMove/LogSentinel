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
            expected_fields = {
                "system": [],
                "telegram": ["token", "chat_id"],
                "slack_webhook": ["url"],
                "slack_bot": ["token", "slack_channel"],
                "discord": ["url"],
                "hermes": ["url", "secret", "headers"],
                "n8n": ["url", "headers"],
                "webhook": ["url", "headers"],
                "file": ["path", "rotation_mb", "keep_archives"],
            }
            drafts = {}
            guide = page.locator(".notification-howto")

            def select_channel(key):
                kind = "slack" if key.startswith("slack_") else key
                page.locator("select[name='kind']").select_option(kind)
                if kind == "slack":
                    page.locator("select[name='slack_mode']").select_option(
                        key.removeprefix("slack_")
                    )
                return page.locator(f"[data-notification-channel='{key}']")

            for language, prefix in [("en", "How to add"), ("es", "Cómo añadir")]:
                page.get_by_label("Language / Idioma").select_option(language)
                page.wait_for_function(
                    "prefix => document.querySelector('.notification-howto summary').textContent.startsWith(prefix)",
                    arg=prefix,
                )
                for key, fields in expected_fields.items():
                    group = select_channel(key)
                    assert group.is_visible()
                    assert page.locator(".notification-fields:visible").count() == 1
                    assert guide.locator("summary").inner_text().startswith(prefix)
                    visible = page.locator("[data-notification-field]:visible")
                    assert (
                        visible.evaluate_all(
                            "nodes => nodes.map(n => n.dataset.notificationField)"
                        )
                        == fields
                    )
                    assert page.locator(
                        "select[name='slack_mode']"
                    ).is_visible() == key.startswith("slack_")
                    for name in fields:
                        input = group.locator(f"[data-notification-field='{name}']")
                        if language == "en":
                            value = (
                                "10"
                                if name in ("rotation_mb", "keep_archives")
                                else (
                                    '{"X-Test": "synthetic-header"}'
                                    if name == "headers"
                                    else (
                                        "https://synthetic.invalid/" + key
                                        if name == "url"
                                        else (
                                            "xoxb-synthetic-bot-token"
                                            if key == "slack_bot" and name == "token"
                                            else (
                                                "C123"
                                                if name == "slack_channel"
                                                else key + "-draft-" + name
                                            )
                                        )
                                    )
                                )
                            )
                            input.fill(value)
                            drafts[(key, name)] = value
                        assert input.input_value() == drafts[(key, name)]
                        assert (
                            drafts[(key, name)] not in guide.inner_text()
                            if name not in ("rotation_mb", "keep_archives")
                            else True
                        )
                    assert guide.locator("button").count() == (
                        1 if key in ("hermes", "n8n") else 0
                    )
                    for link in guide.locator("a").all():
                        assert link.get_attribute("rel") == "noopener noreferrer"
                        assert "synthetic" not in link.get_attribute("href")
                    page.set_viewport_size({"width": 390, "height": 844})
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= window.innerWidth"
                    ), key
                    page.set_viewport_size({"width": 1440, "height": 1000})

            select_channel("slack_bot")
            page.get_by_label("Language / Idioma").select_option("en")
            page.get_by_text("How to add Slack with a bot token", exact=True).wait_for()
            assert (
                page.get_by_label("Slack bot token", exact=True).input_value()
                == "xoxb-synthetic-bot-token"
            )
            for theme in ["classic", "paper", "tokyo", "gruvbox", "rose"]:
                page.get_by_label("Theme / Tema").select_option(theme)
                assert (
                    page.get_by_label("Slack bot token", exact=True).input_value()
                    == "xoxb-synthetic-bot-token"
                )
            select_channel("n8n")
            page.get_by_role("button", name="n8n template", exact=True).click()
            page.locator("#modal[open]").wait_for()
            assert "Configure destination" in page.locator("#modal").inner_text()
            page.locator("#close-modal").click()
            guide.locator("summary").focus()
            page.keyboard.press("Enter")
            assert not guide.evaluate("node => node.open")
            page.keyboard.press("Enter")
            assert guide.evaluate("node => node.open")
            assert not requests, [(r.method, r.url) for r in requests]

            # Save only the selected Slack bot fields. Inactive provider drafts
            # must never be submitted; saving and editing must not send messages.
            select_channel("slack_bot")
            page.get_by_role("button", name="Save", exact=True).click()
            page.get_by_text("Configuration saved.", exact=True).wait_for()
            submitted = [
                r.post_data_json
                for r in requests
                if "/api/objects/destination" in r.url
            ][-1]
            assert submitted["token"] == "xoxb-synthetic-bot-token"
            assert submitted["slack_mode"] == "bot"
            assert (
                not {"url", "secret", "headers", "chat_id", "path"} & submitted.keys()
            )
            saved = app.state.store.objects("destination")[0]
            assert saved["token"] == "xoxb-synthetic-bot-token"
            assert saved["url"] == saved["secret"] == saved["chat_id"] == ""
            assert not app.state.store.rows("deliveries")
            page.get_by_role("button", name="Edit", exact=True).click()
            assert page.get_by_label("Slack bot token", exact=True).input_value() == ""
            assert "Saved" in page.get_by_label(
                "Slack bot token", exact=True
            ).get_attribute("placeholder")
            assert (
                page.get_by_label("Slack channel ID", exact=True).input_value()
                == "C123"
            )
            page.get_by_role("button", name="Save", exact=True).click()
            page.get_by_text("Configuration saved.", exact=True).wait_for()
            assert (
                app.state.store.objects("destination")[0]["token"]
                == "xoxb-synthetic-bot-token"
            )
            page.get_by_role("button", name="Edit", exact=True).click()
            page.get_by_label("Language / Idioma").select_option("es")
            page.get_by_text(
                "Cómo añadir Slack con token de bot", exact=True
            ).wait_for()
            page.get_by_label("Canal", exact=True).select_option("file")
            # Provider changes intentionally discard inactive provider fields.
            page.locator(
                "[data-notification-channel='file'] [data-notification-field='path']"
            ).fill("notifications.jsonl")
            page.get_by_role("button", name="Guardar", exact=True).click()
            page.get_by_text("Configuración guardada.", exact=True).wait_for()
            with page.expect_response(
                lambda response: "/api/destinations/" in response.url
                and response.url.endswith("/test")
            ) as delivered:
                page.get_by_role("button", name="Enviar prueba", exact=True).click()
            assert (
                delivered.value.json()["status"] == "delivered"
            ), delivered.value.json()
            page.get_by_text("delivered", exact=True).wait_for()
            assert app.state.store.objects("destination")[0]["token"] == ""
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
            "PASS: login, machine, import, analysis, evidence, mute, 8 provider forms, Slack bot/webhook isolation, draft/language/theme preservation, templates, file delivery, edit and mobile layout"
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)
