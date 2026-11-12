"""The problem list stays readable: joined, ignorable, and closed when quiet."""

import time

import pytest

from helpers import machine_source
from logsentinel.portal import report, triage
from logsentinel.portal.brain_data import BrainConfig, CommandItem, NoteItem


def finding(title="Service keeps failing", severity="HIGH"):
    return dict(title=title, summary="s", severity=severity, category="ops", reasoning="r", next_steps="n")


@pytest.fixture
def stage(client):
    c, store = client
    machine, source = machine_source(c)
    analyzer = c.app.state.analyzer
    counter = [0]

    def log(*messages):
        """Store lines and return their event ids."""
        start = counter[0]
        counter[0] += len(messages)
        store.ingest(store.get("source", source), [
            dict(origin="o%d" % (start + n), service="app", message=m) for n, m in enumerate(messages)])
        return [e["id"] for e in store.events(source_id=source, limit=5000)][start:]

    def report_finding(ids, **options):
        return analyzer.save_finding(machine, finding(**options.pop("finding", {})), ids, notify=False, **options)

    return c, store, machine, log, report_finding


def test_the_same_fault_with_a_different_set_of_lines_joins_its_problem(stage):
    c, store, machine, log, save = stage
    first = save(log("backup failed: disk quota exceeded", "backup job exited with status 1"))
    # Again, with one line the first batch did not have: still the same fault.
    again = save(log("backup failed: disk quota exceeded", "backup job exited with status 1", "backup retry scheduled"))
    assert again == first
    # Something that shares nothing is its own problem.
    other = save(log("certificate for example.invalid expires in 2 days"))
    assert other != first
    # One shared routine line out of three is not the same fault.
    third = save(log("backup retry scheduled", "database connection refused", "pool exhausted"))
    assert third not in (first, other)
    assert len(store.rows("problems")) == 3
    assert store.problem(first)["count"] == 5


def test_an_ignored_problem_stays_ignored_and_silent_when_it_recurs(stage):
    c, store, machine, log, save = stage
    id = save(log("printer queue is paused"))
    assert c.post("/api/problems/%s/ignore" % id, json={}).json() == {"changed": 1}
    before = store.problem(id)["count"]
    analyzer = c.app.state.analyzer
    assert analyzer.save_finding(machine, finding(), log("printer queue is paused"), notify=True) == id
    problem = store.problem(id)
    assert problem["status"] == "ignored" and problem["count"] == before + 1
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM deliveries").fetchone()[0] == 0
    assert c.get("/api/problems/counts").json()["ignored"] == 1
    assert [p["id"] for p in c.get("/api/problems", params={"status": "ignored"}).json()] == [id]
    assert c.get("/api/problems", params={"status": "open"}).json() == []
    # Taken back, it behaves like any other problem again.
    c.post("/api/problems/%s/ignore" % id, json={"ignored": False})
    assert store.problem(id)["status"] == "open"
    assert c.post("/api/problems/unknown/ignore", json={}).status_code == 404


def test_a_resolved_problem_still_reopens(stage):
    c, store, machine, log, save = stage
    id = save(log("out of memory: killed process"))
    c.post("/api/problems/%s/resolve" % id)
    assert save(log("out of memory: killed process")) == id
    assert store.problem(id)["status"] == "open"


def test_quiet_problems_are_resolved_after_the_configured_days(stage, monkeypatch):
    c, store, machine, log, save = stage
    old = save(log("old trouble"))
    fresh = save(log("fresh trouble"))
    ignored = save(log("known noise"))
    triage.set_status(store, [ignored], "ignore")
    now = time.time()
    with store.connect() as db:
        db.execute("UPDATE problems SET last_seen=? WHERE id IN (?,?)", (now - 20 * 86400, old, ignored))
    assert triage.auto_resolve(store, now) == 1
    assert store.problem(old)["status"] == "resolved"
    assert store.problem(fresh)["status"] == "open" and store.problem(ignored)["status"] == "ignored"
    # Off means off.
    with store.connect() as db:
        db.execute("UPDATE problems SET status='open',last_seen=? WHERE id=?", (now - 400 * 86400, old))
    assert c.post("/api/settings", json={"auto_resolve_days": 0}).status_code == 200
    assert triage.auto_resolve(store, now) == 0


def test_bulk_actions_by_selection_and_by_quiet_time(stage):
    c, store, machine, log, save = stage
    a, b, d = save(log("alpha fault")), save(log("beta fault")), save(log("delta fault"))
    assert c.post("/api/problems/bulk", json={"action": "ignore", "ids": [a, b]}).json() == {"changed": 2}
    assert c.post("/api/problems/bulk", json={"action": "reopen", "ids": [a]}).json() == {"changed": 1}
    with store.connect() as db:
        db.execute("UPDATE problems SET last_seen=? WHERE id=?", (time.time() - 5 * 86400, a))
    assert c.post("/api/problems/bulk", json={"action": "resolve", "all_quiet_days": 3}).json() == {"changed": 1}
    assert [store.problem(i)["status"] for i in (a, b, d)] == ["resolved", "ignored", "open"]
    assert c.post("/api/problems/bulk", json={"action": "delete", "ids": [a]}).status_code == 400
    assert c.post("/api/problems/bulk", json={"action": "resolve"}).status_code == 400
    assert c.get("/api/problems", params={"status": "nonsense"}).status_code == 400


def test_the_daily_report_says_what_happened_on_each_machine(stage):
    c, store, machine, log, save = stage
    brain = c.app.state.brain
    now = time.time()
    save(log("disk /dev/sda1 has failed SMART check"), finding=dict(title="Disk is failing", severity="CRITICAL"))
    noise = save(log("cups printer paused"), finding=dict(title="Printer paused", severity="LOW"))
    triage.set_status(store, [noise], "ignore")
    brain.data.configure(machine, BrainConfig(enabled=True))
    brain.data.receive_commands(machine, [CommandItem(id="c1", kind="command", observed=now - 60, user="alice", cwd="/srv/shop", project="shop", command="make deploy")])
    brain.data.receive_notes(machine, [NoteItem(id="n1", kind="note", observed=now - 30, agent="claude", project="shop", cwd="/srv/shop", text="Pedido: deploy · Resultado: done")])
    answer = c.get("/api/report/daily").json()
    text = answer["text"]
    assert answer["anything"] and not answer["enabled"]
    assert "A\n" in text and "1 CRITICAL" in text and "[CRITICAL] Disk is failing" in text
    assert "Printer paused" not in text and "1 ignored" in text
    assert "Worked on: shop (1 commands)" in text and "claude, shop: Pedido: deploy" in text
    spanish, _ = report.build(store, brain, language="es")
    assert "Resumen diario de LogSentinel" in spanish and "Se trabajó en: shop (1 órdenes)" in spanish


def test_an_empty_day_says_so(client):
    c, store = client
    text, anything = report.build(store, c.app.state.brain)
    assert not anything and text.endswith("Nothing to report.")


@pytest.mark.asyncio
async def test_the_report_goes_once_a_day_to_unscoped_destinations(stage, monkeypatch):
    c, store, machine, log, save = stage
    c.post("/api/objects/destination", json={"name": "all", "kind": "file", "enabled": True, "path": "all.jsonl"})
    c.post("/api/objects/destination", json={"name": "one machine", "kind": "file", "enabled": True, "path": "one.jsonl", "machine_id": machine})
    c.post("/api/objects/destination", json={"name": "off", "kind": "file", "enabled": False, "path": "off.jsonl"})
    assert not report.due(store)
    assert c.post("/api/settings", json={"daily_report": True, "daily_report_hour": 0}).status_code == 200
    assert report.due(store)
    save(log("disk failed"), finding=dict(title="Disk is failing", severity="CRITICAL"))
    results = await report.send(store, c.app.state.brain, c.app.state.outbox, scheduled=True)
    assert [(r["destination"], r["status"]) for r in results] == [("all", "delivered")]
    assert not report.due(store)  # not again today
    written = (store.directory / "notifications/all.jsonl").read_text()
    assert "LogSentinel daily report" in written and "Disk is failing" in written
    assert not (store.directory / "notifications/one.jsonl").exists()
    # On request it can be sent again, without moving the schedule.
    assert c.post("/api/report/daily/send").json()["results"][0]["status"] == "delivered"
