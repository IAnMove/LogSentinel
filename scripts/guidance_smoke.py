"""Exercise guided fields, profile drafts and scoped filter preview/apply/disable.

Temporary synthetic data only. Browser discovery is stubbed; no model or real
notification service is contacted.
"""
import json
from pathlib import Path
import socket
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright
from logsentinel.portal.app import create_app
from logsentinel.portal.models import Machine, Source


with tempfile.TemporaryDirectory(prefix="sentinel-guidance-") as directory:
    app = create_app(directory, background=False)
    store = app.state.store
    machine = store.put("machine", Machine(name="Guide host", kind="local").model_dump())
    empty = store.put("machine", Machine(name="Empty host").model_dump())
    source = store.put("source", Source(name="Application", kind="push", machine_id=machine, enabled=True).model_dump())
    store.put("source", Source(name="Metrics only", kind="metrics", machine_id=machine, enabled=True).model_dump())
    cfg = store.settings()
    cfg.enabled, cfg.input_budget, cfg.context_tokens = True, 12000, 16384
    cfg.llm.model = "synthetic-reviewer"
    store.set_meta("settings", cfg.model_dump_json())
    messages = ["Started daily-backup.timer.", "Started llm-ram-watchdog.service. ERROR disk failure", '<img src=x onerror="throw Error(1)"> Parser failed', "Failed password for root"]
    store.ingest(store.get("source", source), [dict(origin=str(i), service="systemd", message=message) for i, message in enumerate(messages)])
    now = time.time()
    with store.connect() as db:
        db.execute("UPDATE audit SET created=?", (now - 3000,))
        for i in range(3):
            created = now - 600 + i * 110
            db.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,NULL)", (f"job{i}", machine, "[]", "done", created, created + 100, 1, cfg.model_dump_json()))
            db.execute("INSERT INTO usage VALUES(?,?,?,?,?,?,?,?,?,?,?)", (f"usage{i}", f"job{i}", machine, "[]", "analysis", created + 100, 100, 10, 100, "ok", json.dumps(dict(load_seconds=80, prompt_eval_seconds=2, eval_seconds=3))))
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(.05)
    errors, writes = [], []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("request", lambda request: writes.append(request.url) if request.method == "POST" and request.url.endswith("/api/settings") else None)
            page.route("**/api/model/info*", lambda route: route.fulfill(json={"models": []}))
            page.route("**/api/discovery", lambda route: route.fulfill(json={"hostname": "guide-host", "os": "Synthetic Linux", "llm": []}))
            page.goto(f"http://127.0.0.1:{port}")
            page.get_by_label("Access key", exact=True).fill(store.meta("admin_token"))
            page.get_by_role("button", name="Sign in", exact=True).click()
            nav = page.locator("#nav")
            nav.get_by_role("button", name="Setup wizard", exact=True).click()
            page.get_by_text("Where to find these details", exact=True).wait_for()
            assert not page.locator("#monitor-status").is_visible()
            assert not page.get_by_label("Configured effective context").is_visible()
            page.get_by_role("button", name="2. Choose a machine", exact=True).click()
            assert not page.get_by_label("Name", exact=True).is_visible()
            page.get_by_role("button", name="3. Connect logs", exact=True).click()
            options = page.get_by_label("Source", exact=True).locator("option").all_text_contents()
            assert "Metrics only" not in options and "Application" in options
            page.get_by_label("Source", exact=True).select_option("")
            assert not page.get_by_label("Path (file or folder)").is_visible()
            page.get_by_label("Source type").select_option("folder")
            page.get_by_label("Path (file or folder)").fill("/var/log/synthetic")
            assert page.get_by_label("Folder filename pattern").is_visible()
            page.get_by_label("Language / Idioma").select_option("es")
            assert page.get_by_label("Ruta (archivo o carpeta)").input_value() == "/var/log/synthetic"
            assert page.get_by_label("Patrón de archivos en carpeta").is_visible()
            page.screenshot(path="/tmp/logsentinel-guide-source.png", full_page=True)
            page.get_by_label("Language / Idioma").select_option("en")
            nav.get_by_role("button", name="Coverage and capacity", exact=True).click()
            page.locator(".tuning-summary").get_by_text("The server spends more time loading the model", exact=True).wait_for()
            page.get_by_text("Where model time goes", exact=True).click()
            page.locator(".tuning-summary").get_by_role("cell", name="80 s", exact=True).wait_for()
            page.locator("#machine-scope").select_option(empty)
            page.locator(".tuning-summary").get_by_text("No log sources are active", exact=True).wait_for()
            assert page.locator(".tuning-summary .coverage-signal.warn").count() == 1
            page.locator("#machine-scope").select_option(machine)
            nav.get_by_role("button", name="Model and analysis", exact=True).click()
            page.get_by_label("Profile to prepare").select_option("small")
            assert not writes and store.settings().input_budget == 12000
            page.get_by_role("button", name="Prepare this profile without saving").click()
            assert not writes and store.settings().input_budget == 12000
            assert page.locator("[name=input_budget]").input_value() == "3000"
            page.get_by_label("Language / Idioma").select_option("es")
            assert page.get_by_label("Perfil a preparar").input_value() == "small"
            page.get_by_text("Hay cambios en el formulario sin guardar.", exact=True).wait_for()
            assert page.locator("[name=input_budget]").input_value() == "3000"
            page.get_by_role("button", name="Descartar cambios del formulario").click()
            assert page.locator("[name=input_budget]").input_value() == "12000"
            page.get_by_text("Límites de recepción remota", exact=True).click()
            page.get_by_label("MiB por fuente y hora", exact=True).fill("128")
            page.get_by_label("Eventos por fuente y hora", exact=True).fill("10000")
            assert store.settings().sender_mb_per_hour == 256
            page.get_by_label("Perfil a preparar").select_option("small")
            page.get_by_role("button", name="Preparar este perfil sin guardar").click()
            page.get_by_role("button", name="Guardar ajustes", exact=True).click()
            page.get_by_text("Ajustes aplicados.", exact=True).wait_for()
            assert len(writes) == 1
            assert store.settings().input_budget == 3000
            assert store.settings().llm == cfg.llm
            assert store.settings().enabled and store.settings().verification == "important"
            assert store.settings().sender_mb_per_hour == 128
            assert store.settings().sender_events_per_hour == 10000
            page.get_by_label("Language / Idioma").select_option("en")
            nav.get_by_role("button", name="Rules", exact=True).click()
            card = page.locator(".guide-card").filter(has=page.get_by_role("heading", name="Successful systemd timers", exact=True))
            card.get_by_role("button", name="Preview examples before applying").click()
            dialog = page.locator("#modal")
            dialog.get_by_text("1 matches among 4 sampled logs", exact=False).wait_for()
            assert dialog.locator("img").count() == 0
            assert not store.objects("rule")
            dialog.get_by_role("button", name="Apply filter to this scope").click()
            card.get_by_text("Filter enabled", exact=True).wait_for()
            rules = store.objects("rule")
            assert len(rules) == 1 and rules[0]["machine_id"] == machine and rules[0]["enabled"]
            card.get_by_role("button", name="Disable this filter").click()
            card.get_by_text("Filter saved and disabled", exact=True).wait_for()
            assert not store.objects("rule")[0]["enabled"]
            page.screenshot(path="/tmp/logsentinel-guide-filters.png", full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path="/tmp/logsentinel-guide-mobile.png", full_page=True)
            assert not errors, errors
            browser.close()
        print("PASS: contextual wizard fields, retained drafts EN/ES, scoped model diagnosis, profiles prepare/discard/save, filter preview/apply/disable, escaped evidence and mobile")
    finally:
        server.should_exit = True
        thread.join(timeout=10)
