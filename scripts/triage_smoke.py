"""Walk the triage controls: ignore, the status tabs, reopen, and the daily report preview.

Temporary synthetic data only; no model or notification service is contacted.
"""
from pathlib import Path
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright
from logsentinel.portal.app import create_app
from logsentinel.portal.models import Machine, Source

with tempfile.TemporaryDirectory(prefix="sentinel-triage-") as directory:
    app = create_app(directory, background=False)
    store = app.state.store
    machine = store.put("machine", Machine(name="Web host").model_dump())
    source = store.put("source", Source(name="Journal", kind="push", machine_id=machine, enabled=True).model_dump())
    store.ingest(store.get("source", source), [
        dict(origin="a", service="cups", message="printer queue is paused"),
        dict(origin="b", service="kernel", message="disk sda has failed SMART check"),
    ])
    events = store.events(source_id=source)
    for event, title, severity in ((events[0], "Printer paused", "LOW"), (events[1], "Disk is failing", "CRITICAL")):
        app.state.analyzer.save_finding(machine, dict(title=title, summary="s", severity=severity, category="ops", reasoning="r", next_steps="n"), [event["id"]], notify=False)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(400):
        if server.started:
            break
        time.sleep(.05)
    else:
        raise SystemExit("The portal did not start")
    port = server.servers[0].sockets[0].getsockname()[1]
    errors = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}")
            page.get_by_label("Access key", exact=True).fill(store.meta("admin_token"))
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.locator("#nav").get_by_role("button", name="Problems", exact=True).click()
            page.get_by_role("button", name="Open (2)", exact=True).wait_for()
            row = page.get_by_role("row").filter(has_text="Printer paused")
            row.get_by_role("button", name="Ignore", exact=True).click()
            page.get_by_role("button", name="Open (1)", exact=True).wait_for()
            assert page.get_by_role("row").filter(has_text="Printer paused").count() == 0
            assert page.get_by_role("row").filter(has_text="Disk is failing").count() == 1
            page.get_by_role("button", name="Ignored (1)", exact=True).click()
            ignored = page.get_by_role("row").filter(has_text="Printer paused")
            ignored.get_by_role("button", name="Reopen", exact=True).wait_for()
            assert [p["status"] for p in store.rows("problems") if p["title"] == "Printer paused"] == ["ignored"]
            ignored.get_by_role("button", name="Reopen", exact=True).click()
            page.get_by_role("button", name="Ignored (0)", exact=True).wait_for()
            page.get_by_role("button", name="Open (2)", exact=True).click()
            page.get_by_role("row").filter(has_text="Disk is failing").get_by_role("button", name="Resolve", exact=True).click()
            page.get_by_role("button", name="Resolved (1)", exact=True).wait_for()
            # The daily report can be read before turning it on.
            page.get_by_text("Daily report", exact=True).click()
            page.get_by_text("LogSentinel daily report", exact=False).wait_for()
            page.get_by_label("Send a report every day to the general destinations").check()
            page.get_by_role("button", name="Save daily report", exact=True).click()
            page.get_by_text("Daily report saved", exact=True).wait_for()
            assert store.settings().daily_report
            page.get_by_label("Language / Idioma").select_option("es")
            page.get_by_role("heading", name="Triaje", exact=True).wait_for()
            page.screenshot(path="/tmp/logsentinel-triage.png", full_page=True)
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    if errors:
        raise SystemExit("Browser errors: " + "; ".join(errors))
print("triage smoke passed")
