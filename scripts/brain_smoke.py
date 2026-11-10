"""Walk the Brain view: projects, activity search, inventory changes and a question.

Temporary synthetic data only. The model call is answered by the browser route
stub; nothing leaves this process.
"""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from playwright.sync_api import sync_playwright
from logsentinel.portal.app import create_app
from logsentinel.portal.brain_data import BrainConfig, CommandItem, InventoryItem
from logsentinel.portal.models import Machine


def inventory(observed, **data):
    data["system"] = {"os": "Synthetic Linux 1", "kernel": "6.0", "architecture": "x86_64", "hostname": "host"}
    body = json.dumps(data, sort_keys=True)
    return InventoryItem(id="inv-%d" % observed, kind="inventory", observed=observed, digest=hashlib.sha256(body.encode()).hexdigest(), data=data)


with tempfile.TemporaryDirectory(prefix="sentinel-brain-") as directory:
    app = create_app(directory, background=False)
    store, brain = app.state.store, app.state.brain
    laptop = store.put("machine", Machine(name="Laptop").model_dump())
    server_machine = store.put("machine", Machine(name="Build server").model_dump())
    idle = store.put("machine", Machine(name="Idle host").model_dump())
    now = time.time()
    for machine in (laptop, server_machine):
        brain.data.configure(machine, BrainConfig(enabled=True))
    brain.data.receive_inventory(laptop, inventory(now - 7200, packages={"nginx": "1.0", "curl": "8.0"}))
    brain.data.receive_inventory(laptop, inventory(now - 3600, packages={"nginx": "1.1", "curl": "8.0", "git": "2.4"}))
    brain.data.receive_commands(laptop, [
        CommandItem(id="a1", kind="command", observed=now - 900, user="alice", cwd="/home/alice/shop", project="shop", command="git commit -m checkout"),
        CommandItem(id="a2", kind="command", observed=now - 800, user="alice", cwd="/etc/nginx", project="", command='echo "<img src=x onerror=alert(1)>"'),
    ])
    brain.data.receive_commands(server_machine, [
        CommandItem(id="b1", kind="command", observed=now - 300, user="alice", cwd="/srv/shop", project="shop", command="make deploy"),
    ])
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
    errors, asked = [], []

    def answer(route):
        asked.append(route.request.post_data_json)
        route.fulfill(json={"answer": "On Laptop and Build server.", "records": {"commands": 2, "projects": 2}, "truncated": False})

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on("dialog", lambda dialog: errors.append("dialog: " + dialog.message))
            page.route("**/api/brain/ask", answer)
            page.goto(f"http://127.0.0.1:{port}")
            page.get_by_label("Access key", exact=True).fill(store.meta("admin_token"))
            page.get_by_role("button", name="Sign in", exact=True).click()
            nav = page.locator("#nav")
            nav.get_by_role("button", name="Brain", exact=True).click()
            page.get_by_role("heading", name="Where work happened", exact=True).wait_for()
            # One project, two machines: the answer to "where did I work on it".
            where = page.locator("section.panel").filter(has=page.get_by_role("heading", name="Where work happened", exact=True))
            assert where.get_by_role("button", name="shop", exact=True).count() == 2
            assert where.get_by_role("cell", name="Laptop", exact=True).count() == 2  # shop and /etc/nginx
            assert where.get_by_role("cell", name="Build server", exact=True).count() == 1
            # A command is shown as text, never as markup.
            page.get_by_text('echo "<img src=x onerror=alert(1)>"', exact=True).wait_for()
            assert page.locator("#content img").count() == 0
            changes = page.locator("section.panel").filter(has=page.get_by_role("heading", name="Changes in what is installed", exact=True))
            changes.get_by_role("cell", name="1.0 → 1.1", exact=True).wait_for()
            assert changes.get_by_role("cell", name="Added", exact=True).count() == 1
            # Search narrows the commands.
            page.get_by_label("Search commands and directories").fill("deploy")
            page.get_by_role("button", name="Search", exact=True).first.click()
            page.get_by_text("make deploy", exact=True).wait_for()
            assert page.get_by_text("git commit -m checkout", exact=True).count() == 0
            page.get_by_role("button", name="Clear filters", exact=True).click()
            page.get_by_text("git commit -m checkout", exact=True).wait_for()
            # The preview shows the records before anything is asked.
            page.get_by_label("Question about your machines").fill("where did I work on shop?")
            page.get_by_role("button", name="See what would be sent", exact=True).click()
            dialog = page.locator("#modal")
            dialog.get_by_text('"command": "make deploy"', exact=False).wait_for()
            assert not asked
            page.locator("#close-modal").click()
            page.get_by_role("button", name="Ask", exact=True).click()
            page.get_by_text("On Laptop and Build server.", exact=True).wait_for()
            assert asked[0]["message"] == "where did I work on shop?" and asked[0]["days"] == 30
            # Searching redraws the page; the question and its answer stay.
            page.get_by_label("Search commands and directories").fill("deploy")
            page.get_by_role("button", name="Search", exact=True).first.click()
            page.get_by_text("git commit -m checkout", exact=True).wait_for(state="detached")
            assert page.get_by_label("Question about your machines").input_value() == "where did I work on shop?"
            assert page.get_by_text("On Laptop and Build server.", exact=True).count() == 1
            page.get_by_role("button", name="Clear filters", exact=True).click()
            # Machine scope and language.
            page.locator("#machine-scope").select_option(server_machine)
            page.get_by_text("make deploy", exact=True).wait_for()
            assert page.get_by_text("git commit -m checkout", exact=True).count() == 0
            page.locator("#machine-scope").select_option(idle)
            page.get_by_role("heading", name="No machine is reporting yet", exact=True).wait_for()
            page.get_by_label("Brain enabled").check()
            page.get_by_role("button", name="Save", exact=True).click()
            page.get_by_text("Saved", exact=True).wait_for()
            assert brain.data.config(idle).enabled and brain.data.config(idle).mode == "remote"
            page.get_by_role("button", name="Generate sender token", exact=True).click()
            dialog.get_by_text("LOGSENTINEL_BRAIN_TOKEN=", exact=False).wait_for()
            assert store.meta("brain_token:" + idle)
            page.locator("#close-modal").click()
            page.locator("#machine-scope").select_option("")
            page.get_by_label("Language / Idioma").select_option("es")
            page.get_by_role("heading", name="Dónde se ha trabajado", exact=True).wait_for()
            page.locator("#nav").get_by_role("button", name="Cerebro", exact=True).wait_for()
            page.screenshot(path="/tmp/logsentinel-brain.png", full_page=True)
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    if errors:
        raise SystemExit("Browser errors: " + "; ".join(errors))
print("brain smoke passed")
