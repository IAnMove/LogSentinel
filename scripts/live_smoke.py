"""Walk the live log view and the machine page: stored lines first, then arrivals.

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

with tempfile.TemporaryDirectory(prefix="sentinel-live-") as directory:
    app = create_app(directory, background=False)
    store = app.state.store
    web = store.put("machine", Machine(name="Web host", hostname="192.0.2.10", os="Synthetic Linux").model_dump())
    db = store.put("machine", Machine(name="Database host").model_dump())
    web_logs = store.put("source", Source(name="Web journal", kind="push", machine_id=web, enabled=True).model_dump())
    db_logs = store.put("source", Source(name="Database journal", kind="push", machine_id=db, enabled=True).model_dump())
    store.put("source", Source(name="Never installed", kind="push", machine_id=web, enabled=True).model_dump())
    store.set_meta("health:" + web_logs, '{"status":"ok","heartbeat":%f,"sender":{"build":"1.1.0"}}' % time.time())

    def feed(source, *messages):
        feed.n += 1
        store.ingest(store.get("source", source), [
            dict(origin="%d-%d" % (feed.n, i), service="app", message=m, priority=3 if "ERROR" in m else 6)
            for i, m in enumerate(messages)])
    feed.n = 0
    feed(web_logs, "web started", '<img src=x onerror="throw Error(1)"> request')
    feed(db_logs, "database started")
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
            nav = page.locator("#nav")
            nav.get_by_role("button", name="Live", exact=True).click()
            tail = page.get_by_role("log")
            # What was already stored is there on arrival, from every machine.
            tail.get_by_text("web started", exact=True).wait_for()
            tail.get_by_text("database started", exact=True).wait_for()
            assert tail.get_by_text("Web host", exact=True).count() == 2
            assert tail.locator("img").count() == 0  # a log line is text, never markup
            # A line that arrives later appears by itself.
            feed(db_logs, "ERROR replication lag")
            tail.get_by_text("ERROR replication lag", exact=True).wait_for(timeout=10000)
            assert tail.locator(".live-error").count() == 1
            # Paused: arrivals wait; resumed: they are all there.
            page.get_by_role("button", name="Pause", exact=True).click()
            feed(web_logs, "arrived while paused")
            page.wait_for_timeout(2500)  # one poll interval: the line must not show
            assert tail.get_by_text("arrived while paused", exact=True).count() == 0
            page.get_by_role("button", name="Resume", exact=True).click()
            tail.get_by_text("arrived while paused", exact=True).wait_for()
            page.get_by_label("Filter lines").fill("replication")
            assert tail.locator(".live-line").count() == 1
            page.get_by_label("Filter lines").fill("")
            # Leaving and coming back keeps what was on screen.
            nav.get_by_role("button", name="Observer health", exact=True).click()
            nav.get_by_role("button", name="Live", exact=True).click()
            assert page.get_by_role("log").locator(".live-line").count() == 5
            # The machine page: chooser, then everything about one machine.
            nav.get_by_role("button", name="Machine page", exact=True).click()
            page.get_by_role("heading", name="Choose a machine", exact=True).wait_for()
            page.get_by_role("row").filter(has_text="Web host").get_by_role("button", name="Open machine page").click()
            page.get_by_role("heading", name="Log sources", exact=True).wait_for()
            page.get_by_role("cell", name="192.0.2.10", exact=True).wait_for()
            sources = page.locator("section.panel").filter(has=page.get_by_role("heading", name="Log sources", exact=True))
            assert sources.get_by_role("cell", name="Never connected", exact=True).count() == 1
            assert sources.get_by_role("cell", name="1.1.0", exact=True).count() == 1
            own = page.get_by_role("log")
            own.get_by_text("web started", exact=True).wait_for()
            assert own.get_by_text("database started", exact=True).count() == 0
            feed(web_logs, "only on the web host")
            own.get_by_text("only on the web host", exact=True).wait_for(timeout=10000)
            page.get_by_label("Language / Idioma").select_option("es")
            page.get_by_role("heading", name="Fuentes de logs", exact=True).wait_for()
            page.screenshot(path="/tmp/logsentinel-machine.png", full_page=True)
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    if errors:
        raise SystemExit("Browser errors: " + "; ".join(errors))
print("live smoke passed")
