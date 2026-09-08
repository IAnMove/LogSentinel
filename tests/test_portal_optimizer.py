import json
import time

from test_portal_api import client, machine_source
from logsentinel.portal.model_timing import endpoint_id


def populate(c, s):
    machine, source = machine_source(c)
    other, other_source = machine_source(c)
    s.ingest(
        s.get("source", source),
        [
            dict(
                origin=str(i),
                service="kernel",
                priority=2 if i == 0 else 6,
                message="panic" if i == 0 else "normal activity",
                raw="synthetic",
            )
            for i in range(100)
        ],
    )
    s.ingest(
        s.get("source", other_source),
        [dict(origin="other", message="hello", raw="hello")],
    )
    return machine, source, other, other_source


def test_optimizer_without_measurements_is_honest_and_apply_is_scoped(client):
    c, s = client
    machine, source, other, other_source = populate(c, s)
    before = s.settings().model_dump()
    other_config = s.get("source", other_source)
    old_events = s.events(machine_id=machine)
    response = c.post(f"/api/machines/{machine}/optimize")
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["sample_size"] == 100
    assert not plan["capacity"]["reliable"] and plan["recommended"] is None
    strict = next(o for o in plan["choices"] if o["id"] == "critical")
    assert strict["triggers"] == 1 and strict["omitted_by_policy"] == 99
    assert strict["fits_estimate"] is None
    assert (
        "synthetic" not in response.text
    )  # Does not duplicate raw evidence into proposals.
    assert s.get("source", source)["analysis_mode"] == "all"
    url = f"/api/machines/{machine}/optimize/apply"
    body = dict(plan_id=plan["id"], choice="critical")
    assert c.post(url, json=body).status_code == 400
    assert (
        c.post(
            f"/api/machines/{other}/optimize/apply",
            json=dict(body, acknowledge_coverage=True),
        ).status_code
        == 404
    )
    assert c.post(url, json=dict(body, acknowledge_coverage=True)).status_code == 200
    assert s.get("source", source)["priority_ceiling"] == 2
    assert s.get("source", source)["context_minutes"] == 0
    assert s.get("source", other_source) == other_config
    assert s.settings().model_dump() == before
    assert s.events(machine_id=machine) == old_events
    assert c.post(url, json=dict(body, acknowledge_coverage=True)).status_code == 409


def test_optimizer_rejects_stale_plan_and_requires_global_review(client):
    c, s = client
    machine, source, _, _ = populate(c, s)
    cfg = s.settings()
    cfg.context_tokens = 16384
    s.set_meta("settings", cfg.model_dump_json())
    plan = c.post(f"/api/machines/{machine}/optimize").json()
    c.post("/api/objects/source", json={"id": source, "trigger_terms": "keep this"})
    url = f"/api/machines/{machine}/optimize/apply"
    assert (
        c.post(
            url,
            json=dict(plan_id=plan["id"], choice="warnings", acknowledge_coverage=True),
        ).status_code
        == 409
    )
    plan = c.post(f"/api/machines/{machine}/optimize").json()
    larger = next(o for o in plan["choices"] if o["id"] == "larger_batch")
    old_context = s.settings().context_tokens
    body = dict(plan_id=plan["id"], choice="larger_batch", acknowledge_coverage=True)
    assert c.post(url, json=body).status_code == 400
    assert c.post(url, json=dict(body, acknowledge_global=True)).status_code == 200
    assert s.settings().input_budget == larger["global_patch"]["input_budget"]
    assert s.settings().context_tokens == old_context
    assert not s.settings().enabled


def test_capacity_uses_current_model_only_and_discounts_recent_errors(client):
    c, s = client
    machine, source, _, _ = populate(c, s)
    cfg = s.settings()
    ids = [e["id"] for e in s.events(machine_id=machine)]
    s.mark(ids, "compact")
    now = time.time()
    with s.connect() as db:
        db.execute("UPDATE audit SET created=?", (now - 600,))
        for i in range(3):
            job = "job" + str(i)
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,1,?,NULL)",
                (
                    job,
                    machine,
                    json.dumps(ids),
                    "done",
                    now - 200 + i,
                    now - 180 + i,
                    cfg.model_dump_json(),
                ),
            )
            db.execute(
                "INSERT INTO usage VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    "use" + str(i),
                    job,
                    machine,
                    "[]",
                    "analysis",
                    now - 180 + i,
                    1000,
                    50,
                    20,
                    "ok",
                    json.dumps(
                        dict(
                            provider=cfg.llm.provider,
                            model=cfg.llm.model,
                            endpoint_id=endpoint_id(cfg),
                        )
                    ),
                ),
            )
    plan = c.post(f"/api/machines/{machine}/optimize").json()
    assert plan["capacity"]["reliable"]
    assert plan["capacity"]["batch_seconds"] == 20
    assert plan["recommended"] == "warnings"
    assert (
        next(o for o in plan["choices"] if o["id"] == "current")["fits_estimate"]
        is False
    )
    cfg.llm.model = "different-model"
    s.set_meta("settings", cfg.model_dump_json())
    plan = c.post(f"/api/machines/{machine}/optimize").json()
    assert not plan["capacity"]["reliable"]
    assert not plan["capacity"]["batches"]
