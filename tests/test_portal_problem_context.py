import json
from test_portal_api import client, machine_source
from logsentinel.portal.analysis import ReviewClient
from logsentinel.portal.problem_context import context_for, chat_system
from logsentinel.portal.research import SearchPlan, related_events


def problem_fixture(c, s):
    machine, source = machine_source(c)
    s.ingest(
        s.get("source", source),
        [
            {
                "origin": "seed",
                "message": "request-77 failed",
                "service": "api",
                "timestamp": "2026-09-07T12:00:00Z",
            }
        ],
    )
    evidence = s.events()[0]
    finding = dict(
        title="Failed request",
        summary="Original hypothesis",
        severity="HIGH",
        category="reliability",
        reasoning="Check this hypothesis",
        next_steps="Inspect upstream",
        evidence_ids=[evidence["id"]],
    )
    problem = c.app.state.analyzer.save_finding(
        machine, finding, finding["evidence_ids"]
    )
    s.ingest(
        s.get("source", source),
        [
            {
                "origin": str(i),
                "message": "recent unrelated noise",
                "service": "cron",
                "timestamp": "2026-09-07T12:02:00Z",
            }
            for i in range(150)
        ],
    )
    return machine, source, problem, evidence


def test_problem_context_is_canonical_and_history_isolated(client, monkeypatch):
    c, s = client
    machine, source, problem, evidence = problem_fixture(c, s)
    calls = []

    async def fake(self, payload, **kwargs):
        calls.append(payload)
        return {"answer": "Check upstream", "evidence_ids": [evidence["id"]]}

    monkeypatch.setattr(ReviewClient, "call", fake)
    body = dict(
        machine_id=machine,
        problem_id=problem,
        message="Explain this problem",
        language="en",
    )
    preview = c.post("/api/chat/context", json=body)
    assert preview.status_code == 200, preview.text
    assert calls == []
    payload = preview.json()["payload"]
    assert payload["problem"]["title"] == "Failed request"
    assert payload["machine"]["id"] == machine
    assert [e["id"] for e in payload["events"]] == [evidence["id"]]
    response = c.post("/api/chat", json=body)
    assert response.status_code == 200, response.text
    assert calls == [payload]
    assert response.json()["context"]["payload"] == payload
    assert (
        len(
            c.get(
                "/api/chat/history",
                params={"machine_id": machine, "problem_id": problem},
            ).json()
        )
        == 1
    )
    assert c.get("/api/chat/history", params={"machine_id": machine}).json() == []
    assert (
        c.post("/api/chat", json=dict(body, machine_id="different")).status_code == 400
    )
    assert c.post("/api/chat", json=dict(body, problem_id="missing")).status_code == 404


def test_large_context_reports_omissions_and_rejects_invented_citations(
    client, monkeypatch
):
    c, s = client
    machine, source, problem, evidence = problem_fixture(c, s)
    p = s.problem(problem)
    p["data"]["reasoning"] = "á" * 5000
    p["evidence"][0]["message"] = "長" * 4000
    payload, report = context_for(s, machine, "", "Explain", chat_system("en"), p)
    assert report["input_bytes"] <= report["budget_bytes"]
    assert report["truncated_fields"]
    assert report["excerpted_events"] == [evidence["id"]]

    async def fake(*args, **kwargs):
        return {"answer": "Invented", "evidence_ids": ["invented"]}

    monkeypatch.setattr(ReviewClient, "call", fake)
    result = c.post("/api/chat", json={"problem_id": problem, "message": "Explain"})
    assert result.status_code == 502
    assert not s.objects("chat")


def test_investigation_search_is_bounded_scoped_and_durable(client, monkeypatch):
    c, s = client
    machine, source, problem, evidence = problem_fixture(c, s)
    s.ingest(
        s.get("source", source),
        [
            {
                "origin": "related",
                "message": "request-77 upstream timeout",
                "service": "proxy",
                "timestamp": "2026-09-07T12:01:00Z",
            },
            {
                "origin": "outside",
                "message": "request-77 old",
                "service": "proxy",
                "timestamp": "2026-09-06T12:01:00Z",
            },
        ],
    )
    other_machine, other_source = machine_source(c)
    s.ingest(
        s.get("source", other_source),
        [
            {
                "origin": "other",
                "message": "request-77 another machine",
                "service": "proxy",
                "timestamp": "2026-09-07T12:01:00Z",
            }
        ],
    )
    calls = []

    async def fake(self, payload, **kwargs):
        calls.append((payload, kwargs["kind"]))
        if kwargs["kind"] == "research_plan":
            return {"terms": ["request-77"], "services": []}
        linked = next(
            e for e in payload["events"] if "upstream timeout" in e["message"]
        )
        return {"answer": "Proxy confirms timeout", "evidence_ids": [linked["id"]]}

    monkeypatch.setattr(ReviewClient, "call", fake)
    endpoint = f"/api/problems/{problem}/investigations"
    first = c.post(endpoint, json={"language": "en", "window_minutes": 30})
    assert first.status_code == 200, first.text
    assert c.post(endpoint, json={}).json()["id"] == first.json()["id"]
    assert calls == []
    c.portal.call(c.app.state.researcher.tick)
    job = c.get(endpoint).json()[0]
    assert job["status"] == "completed", job
    assert [kind for _, kind in calls] == ["research_plan", "research"]
    assert job["search"]["matched"] == 1
    assert job["context"]["coverage"]["related_events_sent"] == 1
    assert len(s.rows("problems")) == 1
    assert not s.objects("rule")
    limited, report = related_events(
        s, s.problem(problem), SearchPlan(terms=["request-77"]), 30, max_scan=1
    )
    assert report["scan_limited"] and report["scanned"] == 1


def test_investigation_failure_and_restart_are_explicit(client, monkeypatch):
    c, s = client
    _, _, problem, _ = problem_fixture(c, s)

    async def fake(*args, **kwargs):
        return {"terms": ["x" * 101]}

    monkeypatch.setattr(ReviewClient, "call", fake)
    endpoint = f"/api/problems/{problem}/investigations"
    c.post(endpoint, json={})
    c.portal.call(c.app.state.researcher.tick)
    assert c.get(endpoint).json()[0]["status"] == "error"
    job = c.post(endpoint, json={}).json()
    c.app.state.researcher.save(job, status="running")
    c.app.state.researcher.recover()
    assert s.get("investigation", job["id"])["status"] == "interrupted"
