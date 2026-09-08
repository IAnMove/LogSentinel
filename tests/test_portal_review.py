import asyncio
import json
import time
import httpx
import pytest
from pydantic import ValidationError
from logsentinel.portal.analysis import Analyzer, ReviewClient, safe_error
from logsentinel.portal.models import Finding, Machine
from logsentinel.portal.monitor import Monitor
from logsentinel.portal.store import Store
from tests.test_portal_api import client


def test_recovery_does_not_strand_interrupted_last_attempt(tmp_path):
    s = Store(tmp_path)
    with s.connect() as db:
        for id, status, error in [
            ("crash", "running", None),
            ("old", "retry", "Interrupted"),
            ("failed", "failed", "ReadTimeout"),
        ]:
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,3,?,?)",
                (id, "machine", "[]", status, time.time(), time.time(), "{}", error),
            )
    s.recover()
    jobs = {j["id"]: j for j in s.rows("jobs")}
    assert jobs["crash"]["attempts"] == jobs["old"]["attempts"] == 2
    assert jobs["crash"]["status"] == jobs["old"]["status"] == "retry"
    assert jobs["failed"]["status"] == "failed" and jobs["failed"]["attempts"] == 3


def test_model_list_steps_remain_bounded_and_errors_do_not_echo_input():
    finding = dict(
        title="x", summary="x", severity="HIGH", category="x", evidence_ids=["e"]
    )
    assert (
        Finding(**finding, next_steps=["Check disk", "Check memory"]).next_steps
        == "- Check disk\n- Check memory"
    )
    with pytest.raises(ValidationError) as exc:
        Finding(**finding, next_steps={"private-log-content": "secret"})
    assert "private-log-content" not in safe_error(exc.value)
    with pytest.raises(ValidationError):
        Finding(**finding, next_steps=["x" * 4001])


@pytest.mark.asyncio
async def test_default_analysis_does_not_revisit_old_context(tmp_path):
    s = Store(tmp_path)
    machine = s.put("machine", Machine(name="test").model_dump())
    source = {"id": "src", "machine_id": machine}
    s.ingest(source, [{"origin": "old", "message": "old"}])
    s.mark([e["id"] for e in s.events()], "reviewed")
    s.ingest(source, [{"origin": "new", "message": "new error"}])
    a = Analyzer(s)
    seen = []

    async def fake(payload, **kwargs):
        seen.extend(g["message"] for g in payload["groups"])
        return {"findings": []}

    a.client.call = fake
    await a.cycle()
    await a.cycle()
    assert seen == ["new error"]
    assert a.outcome == "no_events"


def test_context_reaches_past_5000_and_does_not_cross_sources(tmp_path):
    s = Store(tmp_path)
    source = {"id": "src", "machine_id": "m"}
    s.ingest(
        source,
        [
            {"origin": str(i), "timestamp": "2020-01-01T00:00:00Z", "message": "old"}
            for i in range(5100)
        ],
    )
    s.ingest(
        source,
        [
            {"origin": "near", "timestamp": "2026-01-01T00:01:00Z", "message": "near"},
            {"origin": "hit", "timestamp": "2026-01-01T00:02:00Z", "message": "error"},
        ],
    )
    s.ingest(
        {"id": "other", "machine_id": "m"},
        [{"origin": "other", "timestamp": "2026-01-01T00:02:00Z", "message": "other"}],
    )
    hit = s.events(source_id="src", offset=5101)[0]["id"]
    assert {e["origin"] for e in s.context([hit], 120)} == {"near", "hit"}


@pytest.mark.asyncio
async def test_schedule_runs_without_a_manual_request_and_pause_is_separate(tmp_path):
    s = Store(tmp_path)
    a = Analyzer(s)
    monitor = Monitor(s, a, True)
    cfg = s.settings()
    cfg.enabled = True
    s.set_meta("settings", cfg.model_dump_json())
    await monitor.tick()
    first = a.started
    assert first and monitor.state()["last_outcome"] == "no_events"
    await monitor.tick()
    assert a.started == first
    cfg.enabled = False
    s.set_meta("settings", cfg.model_dump_json())
    s.put("machine", {"name": "Remote", "kind": "imported"}, "m")
    s.put(
        "source", {"name": "remote", "machine_id": "m", "kind": "push", "enabled": True}
    )
    state = monitor.state()
    assert state["capture"] == "starting" and state["next_analysis"] is None
    monitor.capture_heartbeat = time.time()
    assert monitor.state()["capture"] == "active"
    monitor.capture_heartbeat -= 31
    assert monitor.state()["capture"] == "delayed"
    cfg.enabled = True
    s.set_meta("settings", cfg.model_dump_json())
    monitor.analyzer.started = None
    await monitor.tick()
    assert a.started >= first


def test_wizard_test_is_bound_to_configuration_and_help_needs_no_machine(
    client, monkeypatch
):
    c, s = client
    captured = []

    async def fake(self, payload, **kw):
        captured.append((payload, kw))
        return (
            {"answer": "Use journal without a path."}
            if kw.get("kind") == "help"
            else {"findings": []}
        )

    monkeypatch.setattr(ReviewClient, "call", fake)
    assert c.post("/api/setup/complete").status_code == 400
    assert c.post("/api/model/test").status_code == 200
    assert c.get("/api/state").json()["setup"]["model_tested"]
    c.post("/api/settings", json={"llm": {"api_key": "do-not-leak"}})
    assert not c.get("/api/state").json()["setup"]["model_tested"]
    answer = c.post("/api/help", json={"message": "Journal path?", "language": "en"})
    assert answer.status_code == 200 and "journal" in answer.json()["answer"]
    assert "do-not-leak" not in json.dumps(captured)
    assert "events" not in captured[-1][0]
    assert "English" in captured[-1][1]["system"]
    machine = c.post("/api/objects/machine", json={"name": "test"}).json()["id"]
    c.post(
        "/api/objects/source",
        json={"machine_id": machine, "name": "remote", "kind": "push", "enabled": True},
    )
    assert c.post("/api/model/test").status_code == 200
    assert c.post("/api/setup/complete").status_code == 200
    assert s.settings().enabled
    assert c.get("/api/state").json()["setup"]["completed"]


def test_log_chat_uses_recent_evidence_and_rejects_other_machine_source(
    client, monkeypatch
):
    c, s = client
    machine = s.put("machine", Machine(name="current").model_dump())
    other = s.put("machine", Machine(name="other").model_dump())
    sid = s.put(
        "source",
        {"name": "test", "machine_id": machine, "kind": "push", "enabled": True},
    )
    s.ingest(
        {"id": sid, "machine_id": machine},
        [{"origin": str(i), "message": "line " + str(i)} for i in range(120)],
    )
    seen = []

    async def fake(self, payload, **kw):
        seen.extend(payload["events"])
        return {"answer": "Limited sample", "evidence_ids": [], "filter": None}

    monkeypatch.setattr(ReviewClient, "call", fake)
    assert (
        c.post(
            "/api/chat",
            json={"machine_id": other, "source_id": sid, "message": "Latest?"},
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/chat",
            json={"machine_id": machine, "source_id": sid, "message": "Latest?"},
        ).status_code
        == 200
    )
    assert seen[0]["message"] == "line 119"
    assert all(e["message"] != "line 0" for e in seen)


@pytest.mark.asyncio
async def test_invalid_verdict_is_accounted_as_error(tmp_path, monkeypatch):
    s = Store(tmp_path)
    cfg = s.settings()
    cfg.llm.provider = "openai"
    s.set_meta("settings", cfg.model_dump_json())
    requests = []

    async def post(self, url, **kwargs):
        requests.append(kwargs["json"])
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"findings":[{"title":"broken"}]}'},
                    }
                ],
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    with pytest.raises(ValidationError):
        await ReviewClient(s).call({"events": []})
    with s.connect() as db:
        row = db.execute(
            "SELECT status,input_tokens,output_tokens FROM usage"
        ).fetchone()
    assert tuple(row) == ("error", 10, 5)
    assert "chat_template_kwargs" not in requests[0]
