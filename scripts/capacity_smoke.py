"""Coverage browser journey: same-window counters, planning, scope, EN/ES, draft-only changes."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
import socket
import tempfile
import threading
import time
import uvicorn
from playwright.sync_api import sync_playwright
from logsentinel.portal.app import create_app
from logsentinel.portal.models import Machine, Source

with tempfile.TemporaryDirectory(prefix="sentinel-capacity-") as directory:
    app = create_app(directory, background=False)
    s = app.state.store
    m = s.put("machine", Machine(name="Test host").model_dump())
    source = s.put(
        "source",
        Source(
            machine_id=m, name="Application", kind="push", enabled=True
        ).model_dump(),
    )
    other = s.put("machine", Machine(name="Empty host").model_dump())
    cfg = s.settings()
    cfg.enabled = True
    cfg.context_tokens = 16384
    s.set_meta("settings", cfg.model_dump_json())
    now = time.time()
    s.ingest(
        s.get("source", source),
        [dict(origin=str(i), service="app", message="test") for i in range(100)],
    )
    events = s.events(source_id=source)
    s.mark([e["id"] for e in events[:20]], "compact")
    s.mark([e["id"] for e in events[20:90]], "capacity")
    with s.connect() as db:
        db.execute("UPDATE audit SET created=?", (now - 5000,))
        db.execute("UPDATE events SET received=?", (now - 1200,))
        for id, created in [("a", now - 1800), ("b", now - 900)]:
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,NULL)",
                (id, m, "[]", "done", created, created + 40, 1, cfg.model_dump_json()),
            )
    problem = app.state.analyzer.save_finding(
        m,
        dict(
            title="Reduced coverage",
            summary="Some events were omitted",
            severity="MEDIUM",
            category="monitor.capacity",
            evidence_ids=[events[20]["id"]],
        ),
        [e["id"] for e in events[20:90]],
    )
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
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}")
            page.get_by_label("Access key").fill(s.meta("admin_token"))
            page.get_by_role("button", name="Sign in").click()
            page.get_by_text("Medium", exact=True).wait_for()
            assert not page.get_by_text("Average", exact=True).count()
            page.get_by_role("button", name="Understand and improve coverage").click()
            page.get_by_role(
                "heading", name="Coverage and capacity", exact=True
            ).wait_for()
            page.get_by_text("Show input and call limits", exact=True).click()
            page.get_by_role(
                "cell", name="5,000 bytes per batch", exact=True
            ).wait_for()
            slider = page.get_by_label("Volume selected for the LLM (%)")
            assert slider.is_enabled()
            slider.fill("10")
            page.get_by_text(
                "That volume would be within the observed rate", exact=False
            ).wait_for()
            page.get_by_label("Language / Idioma").select_option("es")
            page.get_by_role(
                "heading", name="Cobertura y capacidad", exact=True
            ).wait_for()
            page.get_by_text("No están en la cola automática", exact=False).wait_for()
            page.get_by_label("Language / Idioma").select_option("en")
            page.get_by_role("button", name="Prepare larger input budget").click()
            draft = int(page.locator("[name=input_budget]").input_value())
            assert draft > 5000 and s.settings().input_budget == 5000
            page.get_by_text("Draft prepared without saving", exact=False).wait_for()
            page.locator("#nav").get_by_role(
                "button", name="Coverage and capacity", exact=True
            ).click()
            page.locator("#machine-scope").select_option(other)
            page.get_by_text("Still measuring:", exact=False).wait_for()
            assert not page.get_by_label("Volume selected for the LLM (%)").is_enabled()
            page.locator("#machine-scope").select_option(m)
            page.get_by_role("cell", name="Application", exact=True).wait_for()
            page.locator("#nav").get_by_role(
                "button", name="Problems", exact=True
            ).click()
            page.get_by_role(
                "columnheader", name="Evidence events", exact=True
            ).wait_for()
            page.get_by_role("button", name="View more details", exact=True).click()
            page.get_by_role(
                "heading", name="This finding describes coverage", exact=True
            ).wait_for()
            page.locator("#content").get_by_role(
                "button", name="Coverage and capacity", exact=True
            ).click()
            page.get_by_role(
                "heading",
                name="Active configuration and measured performance",
                exact=True,
            ).wait_for()
            page.screenshot(
                path="/tmp/logsentinel-capacity-desktop.png", full_page=True
            )
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path="/tmp/logsentinel-capacity-mobile.png", full_page=True)
            assert page.evaluate(
                "document.documentElement.scrollWidth<=window.innerWidth"
            )
            assert not s.rows("usage")
            browser.close()
        assert not errors, errors
        print(
            "PASS: coverage counts, planning, no-model diagnostics, scoped readiness, EN/ES, evidence labels, draft-only budget, mobile"
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)
