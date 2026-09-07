"""Five real-browser themes: persistence, contrast, forms, language and mobile."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import socket, tempfile, threading, time
import uvicorn
from playwright.sync_api import sync_playwright
from logsentinel.portal.app import create_app
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.telemetry_data import MetricSample, TelemetryConfig


def contrast(a, b):
    def luminance(rgb):
        values = [int(v) / 255 for v in rgb.strip("rgb() ").split(",")[:3]]
        values = [
            v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values
        ]
        return sum(v * weight for v, weight in zip(values, (0.2126, 0.7152, 0.0722)))

    x, y = sorted([luminance(a), luminance(b)])
    return (y + 0.05) / (x + 0.05)


with tempfile.TemporaryDirectory(prefix="sentinel-themes-") as directory:
    app = create_app(directory, background=False)
    store = app.state.store
    machine = store.put(
        "machine",
        Machine(name="Atlas · Mini PC", kind="local", hostname="atlas").model_dump(),
    )
    source = store.put(
        "source",
        Source(
            name="System journal", machine_id=machine, kind="push", enabled=True
        ).model_dump(),
    )
    store.ingest(
        store.get("source", source),
        [
            dict(
                origin=str(i),
                service="sshd",
                message="Authentication failures from 192.0.2.42",
                raw="2026-09-07T18:00:00Z atlas sshd: Authentication failures from 192.0.2.42",
            )
            for i in range(12)
        ],
    )
    event = store.events()[0]
    app.state.analyzer.save_finding(
        machine,
        dict(
            title="Repeated SSH authentication failures",
            summary="12 unsuccessful sign-in attempts were captured. Verify the source address and authentication policy.",
            severity="HIGH",
            category="security.authentication",
            evidence_ids=[event["id"]],
            reasoning="Synthetic evidence for the UI smoke test.",
            next_steps="Inspect related authentication records.",
        ),
        [event["id"]],
        notify=False,
    )
    telemetry = app.state.telemetry
    telemetry.configure(machine, TelemetryConfig(enabled=True))
    for i in range(24):
        telemetry.receive(
            machine,
            MetricSample(
                observed=time.time() - (23 - i) * 3600,
                values={
                    "cpu_pct": 20 + i,
                    "ram_pct": 45 + i / 3,
                    "disk_pct:/": 63,
                    "inode_pct:/": 12,
                },
            ),
        )
    app.state.health.tick()
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
    screenshots = Path("/tmp/logsentinel-themes")
    screenshots.mkdir(exist_ok=True)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1440, "height": 1050})
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(f"http://127.0.0.1:{port}")
            assert page.locator("html").get_attribute("data-theme") == "classic"
            page.get_by_label("Access key").fill(store.meta("admin_token"))
            page.get_by_role("button", name="Sign in", exact=True).click()
            page.get_by_role("button", name="Appearance", exact=True).click()
            assert page.locator(".theme-card").count() == 5
            page.screenshot(path=str(screenshots / "gallery.png"), full_page=True)
            for theme in ["classic", "paper", "tokyo", "gruvbox", "rose"]:
                page.get_by_label("Theme / Tema").select_option(theme)
                page.locator("#machine-scope").select_option("")
                page.get_by_role("button", name="Overview", exact=True).click()
                page.screenshot(
                    path=str(screenshots / (theme + ".png")), full_page=True
                )
                for foreground, background in [
                    ("--ink", "--surface"),
                    ("--muted", "--surface"),
                    ("--button-ink", "--accent"),
                    ("--error-ink", "--error-bg"),
                    ("--warn-ink", "--warn-bg"),
                    ("--rail-ink", "--rail"),
                    ("--rail-muted", "--rail"),
                ]:
                    colors = page.evaluate(
                        """([fg,bg]) => { const n=document.createElement('span'); n.style.color='var('+fg+')'; n.style.backgroundColor='var('+bg+')'; document.body.append(n); const s=getComputedStyle(n), colors=[s.color,s.backgroundColor]; n.remove(); return colors; }""",
                        [foreground, background],
                    )
                    assert contrast(*colors) >= 4.5, (
                        theme,
                        foreground,
                        colors,
                        contrast(*colors),
                    )
                page.get_by_role("button", name="Observer health", exact=True).click()
                page.get_by_text("Automatic supervision", exact=True).wait_for()
                page.get_by_role("button", name="Metrics", exact=True).click()
                page.get_by_role("button", name="View metrics and configure").click()
                page.get_by_role("img").first.wait_for()
            page.get_by_role("button", name="Model and analysis", exact=True).click()
            model = page.locator('input[name="model"]')
            model.fill("unsaved-model-choice")
            page.get_by_label("Theme / Tema").select_option("paper")
            assert model.input_value() == "unsaved-model-choice"
            page.get_by_role("button", name="Desktop", exact=True).click()
            page.get_by_role("button", name="Create widget key", exact=True).click()
            page.get_by_role("heading", name="Private widget configuration").wait_for()
            import json

            pairing = json.loads(page.locator("#modal pre").first.inner_text())
            assert (
                page.request.get(
                    f"http://127.0.0.1:{port}/widget/status",
                    headers={"Authorization": "Bearer " + pairing["token"]},
                ).status
                == 200
            )
            page.locator("#close-modal").click()
            with page.expect_response(
                lambda response: response.url.endswith("/api/widget/token")
                and response.request.method == "DELETE"
            ) as revoked:
                page.get_by_role(
                    "button", name="Revoke widget access", exact=True
                ).click()
            assert revoked.value.status == 200
            assert (
                page.request.get(
                    f"http://127.0.0.1:{port}/widget/status",
                    headers={"Authorization": "Bearer " + pairing["token"]},
                ).status
                == 401
            )
            page.get_by_label("Language / Idioma").select_option("es")
            page.reload()
            assert page.locator("html").get_attribute("lang") == "es"
            assert page.locator("html").get_attribute("data-theme") == "paper"
            page.set_viewport_size({"width": 390, "height": 844})
            page.get_by_role("button", name="Apariencia", exact=True).click()
            page.screenshot(path=str(screenshots / "mobile.png"), full_page=True)
            assert page.evaluate(
                "document.documentElement.scrollWidth <= innerWidth"
            ), "Horizontal page overflow"
            brand = page.locator("aside .brand").bounding_box()
            controls = page.locator(".display-controls").bounding_box()
            assert (
                brand["y"] >= controls["y"] + controls["height"]
            ), "Mobile controls overlap the brand"
            assert not errors, errors
            browser.close()
        print(
            "Five themes passed: contrast, persistence, ES/EN, metrics, health and mobile. Screenshots: "
            + str(screenshots)
        )
    finally:
        server.should_exit = True
        thread.join(timeout=10)
