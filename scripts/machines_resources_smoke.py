"""Isolated browser journey for scoped controls, resource details and optimization."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import socket
import tempfile
import threading
import time

import uvicorn
from playwright.sync_api import sync_playwright, expect
from logsentinel.portal.app import create_app
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.telemetry_data import MetricSample, TelemetryConfig

with tempfile.TemporaryDirectory(prefix="sentinel-machines-ui-") as folder:
    root = Path(folder)
    disk = root / "example-disk"
    (disk / "large-folder").mkdir(parents=True)
    (disk / "large-folder/file").write_bytes(b"x" * 100000)
    app = create_app(root / "data", background=False)
    store, telemetry = app.state.store, app.state.telemetry
    machine = store.put("machine", Machine(name="Atlas", kind="local").model_dump())
    other = store.put("machine", Machine(name="Second host").model_dump())
    source = store.put(
        "source",
        Source(
            name="Remote log", machine_id=machine, kind="push", enabled=True
        ).model_dump(),
    )
    store.ingest(
        store.get("source", source),
        [
            dict(
                origin=str(i),
                service="kernel",
                priority=2 if i == 0 else 6,
                message="panic" if i == 0 else "normal",
                raw="synthetic",
            )
            for i in range(100)
        ],
    )
    telemetry.configure(
        machine,
        TelemetryConfig(
            enabled=True, mode="local", disk_paths=[str(disk)], discover_disks=False
        ),
    )
    gb = 1024**3
    for i in range(12):
        telemetry.receive(
            machine,
            MetricSample(
                observed=time.time() - (11 - i) * 60,
                values={
                    "cpu_pct": 15 + i,
                    "cpu_count": 2,
                    "cpu_thread_pct:0": 20 + i,
                    "cpu_thread_pct:1": 10 + i,
                    "ram_pct": 50,
                    "ram_total_bytes": 16 * gb,
                    "ram_used_bytes": 8 * gb,
                    "ram_free_bytes": 2 * gb,
                    "ram_shared_bytes": 0.5 * gb,
                    "ram_buffers_bytes": 0.1 * gb,
                    "ram_cached_bytes": 6 * gb,
                    "ram_buff_cache_bytes": 6.1 * gb,
                    "ram_available_bytes": 8 * gb,
                    "swap_pct": 10,
                    "swap_used_bytes": 0.2 * gb,
                    "swap_total_bytes": 2 * gb,
                    "disk_pct:" + str(disk): 65,
                    "disk_total_bytes:" + str(disk): 100 * gb,
                    "disk_used_bytes:" + str(disk): 60 * gb,
                    "disk_free_bytes:" + str(disk): 40 * gb,
                    "disk_available_bytes:" + str(disk): 35 * gb,
                },
            ),
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
        time.sleep(0.02)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}")
            page.locator("#access-key").fill(store.meta("admin_token"))
            page.locator("#login-form button").click()
            expect(page.locator("#shell")).to_be_visible()
            page.locator("#machine-scope").select_option(machine)
            page.locator("#nav").get_by_role(
                "button", name="Metrics", exact=True
            ).click()
            expect(page.locator(".cpu-thread")).to_have_count(2)
            expect(page.get_by_text("Shared", exact=True)).to_be_visible()
            expect(page.locator(".disk-space-bar")).to_have_count(1)
            expect(page.locator(".disk-space-reserved")).to_be_visible()
            page.screenshot(
                path="/tmp/logsentinel-resources-desktop.png", full_page=True
            )
            page.get_by_role("button", name="More disk info", exact=True).click()
            assert not store.objects("disk_scan")
            page.get_by_role(
                "button", name="Calculate largest folders", exact=True
            ).click()
            expect(page.locator("#modal-content")).to_contain_text(
                "large-folder", timeout=10000
            )
            page.locator("#close-modal").click()
            page.locator("#nav").get_by_role(
                "button", name="Machines", exact=True
            ).click()
            page.get_by_role("button", name="Pause this machine", exact=True).click()
            expect(
                page.get_by_role("button", name="Resume this machine", exact=True)
            ).to_be_visible()
            assert store.monitoring_active(other) and not store.monitoring_active(
                machine
            )
            page.get_by_role("button", name="Optimize", exact=True).click()
            expect(page.locator("#modal-content")).to_contain_text(
                "Proposal prepared", timeout=15000
            )
            page.get_by_label("Proposal to apply").select_option("critical")
            expect(
                page.get_by_role("button", name="Apply this proposal", exact=True)
            ).to_be_disabled()
            page.get_by_label(
                "I have reviewed the changes and coverage loss", exact=True
            ).check()
            page.get_by_role("button", name="Apply this proposal", exact=True).click()
            expect(page.locator("#modal-content")).to_contain_text("Proposal applied")
            assert not store.monitoring_active(machine)
            assert store.get("source", source)["priority_ceiling"] == 2
            page.locator("#close-modal").click()
            page.get_by_role("button", name="Delete machine", exact=True).click()
            expect(page.locator("#modal-content")).to_contain_text("Original files")
            page.get_by_role("button", name="Cancel", exact=True).click()
            assert store.get("machine", machine)
            page.get_by_label("Language / Idioma").select_option("es")
            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("button", name="Optimizar", exact=True).click()
            expect(page.locator("#modal-content")).to_contain_text(
                "Propuesta preparada", timeout=15000
            )
            assert page.evaluate(
                "()=>document.documentElement.scrollWidth <= innerWidth"
            )
            page.screenshot(
                path="/tmp/logsentinel-optimizer-mobile.png", full_page=True
            )
            page.locator("#close-modal").click()
            page.get_by_role("button", name="Borrar máquina", exact=True).click()
            page.get_by_role(
                "button", name="Sí, borrar máquina y datos", exact=True
            ).click()
            expect(page.locator("#modal-content")).to_contain_text(
                "Máquina y datos asociados eliminados", timeout=15000
            )
            assert not store.get("machine", machine)
            assert store.get("machine", other)
            assert (disk / "large-folder/file").exists()
            assert not errors, errors
            browser.close()
        print(
            "Scoped pause, optimizer review/apply, deletion confirmation/cascade, RAM/threads/disks, folder inspection, EN/ES and mobile passed."
        )
    finally:
        server.should_exit = True
        thread.join(10)
