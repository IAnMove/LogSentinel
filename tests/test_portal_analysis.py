import asyncio
import pytest
from logsentinel.portal.store import Store
from logsentinel.portal.models import Machine
from logsentinel.portal.analysis import Analyzer, compact, interleave_services
from logsentinel.portal.rules import redact


@pytest.fixture
def data(tmp_path):
    s = Store(tmp_path)
    m = s.put("machine", Machine(name="server").model_dump())
    source = {"id": "s", "machine_id": m}
    s.ingest(
        source,
        [
            {"origin": "1", "message": "connection pool exhausted", "service": "app"},
            {"origin": "2", "message": "a different problem", "service": "disk"},
        ],
    )
    return s, m


def test_context_is_shared_with_quiet_services_without_losing_events():
    events = [{"id": "busy-" + str(i), "service": "python"} for i in range(100)] + [
        {"id": "ssh", "service": "sshd"},
        {"id": "disk", "service": "kernel"},
    ]
    result = interleave_services(events)
    assert [e["service"] for e in result[:3]] == ["python", "sshd", "kernel"]
    assert len(result) == len(events)
    assert [e for e in result if e["service"] == "python"] == events[:100]
    assert interleave_services(events, 1)[0]["service"] == "sshd"


@pytest.mark.asyncio
async def test_multiple_findings_persist_and_references_are_checked(data):
    s, m = data
    a = Analyzer(s)
    calls = 0

    async def fake(payload, **kwargs):
        nonlocal calls
        calls += 1
        entries = payload.get("groups", payload.get("events", []))
        return {
            "findings": [
                {
                    "title": e.get("message", "x"),
                    "summary": "check evidence",
                    "severity": "HIGH",
                    "category": "reliability",
                    "evidence_ids": [e["id"]],
                }
                for e in entries
            ]
        }

    a.client.call = fake
    await a.cycle()
    assert len(s.rows("problems")) == 2
    assert all(s.problem(p["id"])["evidence"] for p in s.rows("problems"))
    assert calls == 2
    assert s.rows("jobs")[0]["status"] == "done"


@pytest.mark.asyncio
async def test_verification_failure_preserves_first_pass_and_explicit_partial_coverage(
    data,
):
    s, machine = data
    analyzer = Analyzer(s)

    async def fake(payload, **kwargs):
        if kwargs.get("kind") == "investigation":
            raise ValueError("verification timeout")
        return {
            "findings": [
                {
                    "title": "Capacity issue",
                    "summary": "Check the pool",
                    "severity": "HIGH",
                    "category": "reliability",
                    "evidence_ids": [payload["groups"][0]["id"]],
                }
            ]
        }

    analyzer.client.call = fake
    result = await analyzer.cycle()
    assert result["errors"] == 1
    assert s.rows("jobs")[0]["status"] == "retry"
    await analyzer.cycle()
    await analyzer.cycle()
    assert s.rows("jobs")[0]["status"] == "partial"
    assert len(s.rows("problems")) == 1
    problem = s.problem(s.rows("problems")[0]["id"])
    assert "Preliminary" in problem["data"]["reasoning"]
    assert all(e["status"] == "compact" for e in s.events())


@pytest.mark.asyncio
async def test_bad_references_do_not_turn_into_clean_analysis(data):
    s, m = data
    a = Analyzer(s)

    async def fake(*args, **kwargs):
        return {
            "findings": [
                {
                    "title": "x",
                    "summary": "x",
                    "severity": "HIGH",
                    "category": "x",
                    "evidence_ids": ["invented"],
                }
            ]
        }

    a.client.call = fake
    await a.cycle()
    assert s.rows("problems") == []
    assert s.rows("jobs")[0]["status"] == "retry"
    assert s.events()[0]["status"] == "error"


@pytest.mark.asyncio
async def test_cancellation_retains_recoverable_job(data):
    s, m = data
    a = Analyzer(s)

    async def fake(*args, **kwargs):
        raise asyncio.CancelledError()

    a.client.call = fake
    with pytest.raises(asyncio.CancelledError):
        await a.cycle()
    assert s.rows("jobs")[0]["status"] == "retry"
    assert len(s.events()) == 2
    assert s.rows("jobs")[0]["attempts"] == 0


def test_compaction_preserves_count_and_ids():
    events = [
        {
            "id": str(i),
            "source_id": "s",
            "service": "x",
            "message": "same",
            "timestamp": str(i),
        }
        for i in range(100)
    ]
    groups, ids, omitted = compact(events, 1000)
    assert groups[0]["count"] == 100
    assert len(groups[0]["event_ids"]) == 100
    assert groups[0]["first"] == "0" and groups[0]["last"] == "99"
    assert not omitted


def test_redaction():
    assert "abc123" not in redact("Authorization: Bearer abc123")
    assert "hunter2" not in redact("password=hunter2")
    assert "AKIAAAAAAAAAAAAAAAAA" not in redact("aws AKIAAAAAAAAAAAAAAAAA used")
    assert "xoxb-1234567890-token" not in redact("Slack xoxb-1234567890-token")
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcdeffake"
    assert jwt not in redact("auth " + jwt)
    pem = "-----BEGIN PRIVATE KEY-----\nabcDEF1234567890\n-----END PRIVATE KEY-----"
    assert "abcDEF1234567890" not in redact(pem)
    assert "secret-hook" not in redact(
        "https://discord.com/api/webhooks/1/secret-hook"
    )


def test_source_filter_uses_priority_and_case_insensitive_terms():
    events = [
        {"id": "critical", "message": "kernel CRITICAL failure", "priority": 6},
        {"id": "priority", "message": "routine message", "priority": 3},
        {"id": "quiet", "message": "routine message", "priority": 6},
    ]
    triggers, sampled = Analyzer._trigger_events(
        events,
        {
            "analysis_mode": "adaptive",
            "priority_ceiling": 4,
            "trigger_terms": "critical",
        },
    )
    assert {event["id"] for event in triggers} == {"critical", "priority"}
    assert sampled == ["quiet"]


def test_context_uses_minutes_and_keeps_original_events(data):
    store, machine = data
    source = {"id": "timed", "machine_id": machine}
    store.ingest(
        source,
        [
            {
                "origin": "before",
                "timestamp": "2026-01-01T00:00:00+00:00",
                "message": "before",
            },
            {
                "origin": "hit",
                "timestamp": "2026-01-01T00:04:00+00:00",
                "message": "ERROR hit",
            },
            {
                "origin": "after",
                "timestamp": "2026-01-01T00:08:00+00:00",
                "message": "after",
            },
            {
                "origin": "far",
                "timestamp": "2026-01-01T00:20:00+00:00",
                "message": "far",
            },
        ],
    )
    hit = [
        event for event in store.events(source_id="timed") if event["origin"] == "hit"
    ][0]
    context = store.context([hit["id"]], seconds=300)
    assert {event["origin"] for event in context} == {"before", "hit", "after"}
    assert len(store.events(source_id="timed")) == 4


@pytest.mark.asyncio
async def test_capacity_is_visible_and_preserves_original(data):
    s, m = data
    cfg = s.settings()
    cfg.input_budget = 512
    s.set_meta("settings", cfg.model_dump_json())
    source = {"id": "oversize", "machine_id": m}
    s.ingest(source, [{"origin": "large", "service": "test", "message": "x" * 3000}])
    a = Analyzer(s)

    async def healthy(*args, **kwargs):
        return {"findings": []}

    a.client.call = healthy
    await a.cycle()
    assert len(s.events(status="oversized")) >= 1
    assert any(p["data"].find("monitor.capacity") >= 0 for p in s.rows("problems"))
    assert any(e["message"] == "x" * 3000 for e in s.events(status="oversized"))
