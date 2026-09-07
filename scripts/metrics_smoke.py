"""Real browser telemetry settings, automatic capture, history and LLM trends."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import socket, tempfile, threading, time
import uvicorn
from playwright.sync_api import sync_playwright
from logsentinel.portal.app import create_app
from logsentinel.portal.models import Machine
from logsentinel.portal.telemetry_data import MetricSample

with tempfile.TemporaryDirectory(prefix="sentinel-metrics-") as directory:
    app = create_app(directory)
    store = app.state.store
    machine = store.put(
        "machine", Machine(name="Metrics test", kind="local").model_dump()
    )
    app.state.telemetry.sampler.sample = lambda paths: MetricSample(
        values={
            "cpu_pct": 25,
            "ram_pct": 60,
            "swap_total_bytes": 0,
            "disk_pct:/": 40,
            "inode_pct:/": 10,
            "load1": 1,
            "uptime_seconds": 86400,
        }
    )
    calls = []

    async def model(payload, **kwargs):
        calls.append(payload)
        return {
            "answer": "Capacity is adequate in the supplied samples.",
            "metrics": ["cpu_pct", "ram_pct"],
            "next_checks": ["Inspect expected workload"],
            "incomplete_coverage": "Only a short sample history is available.",
        }

    app.state.telemetry.client.call = model
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
            page = browser.new_page(
                viewport={"width": 1440, "height": 1000}, locale="es-ES"
            )
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}")
            page.get_by_label("Access key").fill(store.meta("admin_token"))
            page.get_by_role("button", name="Sign in").click()
            page.get_by_role("button", name="Metrics", exact=True).click()
            page.get_by_role("button", name="View metrics and configure").click()
            page.get_by_text("Configure collection and alerts", exact=True).click()
            page.get_by_label("Enable measurements", exact=True).check()
            page.get_by_label("Metrics source", exact=True).select_option("local")
            page.get_by_label("Measurement interval (seconds)").fill("10")
            page.get_by_role("button", name="Save metrics configuration").click()
            page.get_by_text("Measurements active", exact=True).wait_for(timeout=15000)
            page.get_by_role(
                "img", name="CPU · Hourly peaks and averages, last 24 hours"
            ).wait_for()
            assert calls == []
            page.get_by_role("button", name="Analyze trends", exact=True).click()
            page.get_by_text(
                "Capacity is adequate in the supplied samples.", exact=True
            ).wait_for(timeout=15000)
            assert len(calls) == 1 and calls[0]["machine"]["id"] == machine
            page.get_by_text("- Inspect expected workload", exact=True).wait_for()
            page.get_by_text(
                "Only a short sample history is available.", exact=True
            ).wait_for()
            page.get_by_text("Context sent to the model", exact=True).click()
            page.get_by_label("Language / Idioma").select_option("es")
            page.get_by_role(
                "button", name="Analizar tendencias", exact=True
            ).wait_for()
            page.get_by_text("Mediciones activas", exact=True).wait_for()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.screenshot(path="/tmp/logsentinel-metrics.png", full_page=True)
            browser.close()
        assert not errors, errors
        assert app.state.telemetry.status(machine)["retained_samples"] >= 1
        print(
            "PASS: metrics configuration, continuous sampling, charts, durable trend analysis, EN/ES and mobile"
        )
    finally:
        server.should_exit = True
        thread.join(timeout=5)
