"""What goes out to one destination never carries another destination's credentials."""

import asyncio
import json

from logsentinel.portal.notify import Outbox, enqueue
from tests.helpers import machine_source

URL = "https://n8n.example.invalid/webhook/7f3a9c-very-secret-path"


def problem_quoting_the_url_then_a_destination_with_it(c, store):
    machine, sid = machine_source(c)
    c.post("/api/objects/destination", json={"name": "Archivo", "kind": "file", "enabled": True, "min_severity": "LOW"})
    store.ingest(store.get("source", sid), [dict(origin="x", message=f"deploy hook failed: POST {URL} returned 500", service="deploy")])
    event = store.events(limit=5)[0]
    finding = dict(title="Hook failed", summary=f"The hook {URL} failed", severity="HIGH", category="application", evidence_ids=[event["id"]])
    pid = c.app.state.analyzer.save_finding(machine, finding, [event["id"]], notify=False)
    # Only now does the URL become a protected secret.
    c.post("/api/objects/destination", json={"name": "n8n", "kind": "n8n", "enabled": True, "url": URL})
    enqueue(store, pid)
    return pid


def test_the_file_destination_does_not_receive_the_other_destinations_webhook(client, tmp_path):
    c, store = client
    problem_quoting_the_url_then_a_destination_with_it(c, store)
    asyncio.run(Outbox(store).drain())
    written = "".join(p.read_text() for p in (store.directory / "notifications").glob("*") if p.is_file())
    assert "Hook failed" in written, "the alert itself was delivered"
    assert "very-secret" not in written


def test_the_state_endpoint_hides_the_secret_inside_queued_deliveries(client):
    c, store = client
    problem_quoting_the_url_then_a_destination_with_it(c, store)
    assert any("very-secret" in r["payload"] for r in store.rows("deliveries")), "the stored payload predates the secret"
    assert "very-secret" not in c.get("/api/state").text
