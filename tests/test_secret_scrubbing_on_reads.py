"""Every way of reading a problem hides the credentials the portal itself holds."""

import json

from tests.helpers import machine_source

WEBHOOK = "https://hooks.example.invalid/services/T000/B000/synthetic-webhook-secret-7788"


def add_destination(c, store):
    c.post(
        "/api/objects/destination",
        json={"name": "Chat", "kind": "slack", "enabled": True, "url": WEBHOOK},
    )
    assert any(d.get("url") == WEBHOOK for d in store.objects("destination")), "the destination must hold the secret"


def problem_quoting_a_destination_url(c, store, destination_first=True):
    machine, sid = machine_source(c)
    if destination_first:
        add_destination(c, store)
    store.ingest(
        store.get("source", sid),
        [dict(origin="a", message=f"deploy hook failed: POST {WEBHOOK} returned 500", service="deploy")],
    )
    event = store.events(limit=10)[0]
    finding = dict(title="Deploy hook failed", summary=f"The hook {WEBHOOK} failed", severity="HIGH",
                   category="application", evidence_ids=[event["id"]])
    pid = c.app.state.analyzer.save_finding(machine, finding, finding["evidence_ids"])
    if not destination_first:
        add_destination(c, store)
    return pid


def test_the_state_endpoint_hides_a_secret_that_was_added_after_the_problem_was_saved(client):
    c, store = client
    problem_quoting_a_destination_url(c, store, destination_first=False)
    assert "synthetic-webhook-secret" in json.dumps(store.rows("problems")), "the stored problem predates the secret"
    assert "synthetic-webhook-secret" not in c.get("/api/state").text


def test_the_problem_list_does_not_either(client):
    c, store = client
    problem_quoting_a_destination_url(c, store, destination_first=False)
    assert "synthetic-webhook-secret" not in c.get("/api/problems").text


def test_the_prompt_meant_for_an_outside_model_hides_destination_secrets(client):
    c, store = client
    pid = problem_quoting_a_destination_url(c, store)
    text = c.get(f"/api/problems/{pid}/prompt").text
    assert "synthetic-webhook-secret" not in text
    assert "deploy hook failed" in text, "the evidence itself must still be there"


def test_the_prompt_still_hides_the_model_key(client):
    c, store = client
    pid = problem_quoting_a_destination_url(c, store)
    settings = store.settings()
    settings.llm.api_key = "sk-synthetic-model-key-424242"
    store.set_meta("settings", settings.model_dump_json())
    store.ingest(store.get("source", store.objects("source")[0]["id"]),
                 [dict(origin="b", message="auth used sk-synthetic-model-key-424242 here", service="deploy")])
    assert "424242" not in json.dumps(c.get(f"/api/problems/{pid}/prompt").text)
