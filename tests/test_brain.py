"""The brain: what each machine has, what changed, and where work was done."""

import hashlib
import json
import time

import pytest

from helpers import machine_source
from logsentinel.portal import brain_collect
from logsentinel.portal.analysis import ReviewClient
from logsentinel.portal.brain import terms
from logsentinel.portal.brain_data import differences
from logsentinel.portal.brain_hook import MARK, install_hook, remove_hook


def inventory(observed, **data):
    data.setdefault("system", {"os": "Example Linux 1", "kernel": "6.0", "architecture": "x86_64", "hostname": "host"})
    body = json.dumps(data, sort_keys=True)
    return dict(
        id="inv-%d" % observed,
        kind="inventory",
        observed=observed,
        digest=hashlib.sha256(body.encode()).hexdigest(),
        data=data,
        errors=[],
    )


def command(n, observed, text, cwd="/srv/alice/shop", project="shop", user="alice"):
    return dict(id="cmd-%s" % n, kind="command", observed=observed, user=user, cwd=cwd, project=project, command=text)


@pytest.fixture
def remote(client):
    """A machine with remote brain reports enabled and a sender token."""
    c, store = client
    machine, _ = machine_source(c)
    assert c.post("/api/brain/%s/config" % machine, json={"enabled": True}).status_code == 200
    token = c.post("/api/brain/%s/token" % machine).json()["token"]
    return c, store, machine, {"Authorization": "Bearer " + token}


def send(c, machine, headers, *items):
    return c.post("/ingest-brain/" + machine, json={"items": list(items)}, headers=headers)


def test_differences_name_what_was_added_removed_and_changed():
    before = {"packages": {"nginx": "1.0", "curl": "8.0"}, "ports": {"tcp 0.0.0.0:22": "listening"}}
    after = {"packages": {"nginx": "1.1", "git": "2.4"}, "ports": {"tcp 0.0.0.0:22": "listening"}}
    assert differences(before, after) == [
        ("packages", "removed", "curl", "8.0", ""),
        ("packages", "added", "git", "", "2.4"),
        ("packages", "changed", "nginx", "1.0", "1.1"),
    ]


def test_a_category_that_could_not_be_read_is_not_reported_as_emptied():
    before = {"packages": {"nginx": "1.0"}, "users": {"alice": "uid 1000, /bin/bash"}}
    after = {"users": {"alice": "uid 1000, /bin/bash"}}  # the package reader failed
    assert differences(before, after) == []


def test_reception_needs_the_machine_token_and_an_enabled_brain(remote):
    c, store, machine, headers = remote
    item = command(1, time.time(), "git status")
    assert send(c, machine, {"Authorization": "Bearer wrong"}, item).status_code == 401
    assert send(c, machine, {}, item).status_code == 401
    assert send(c, machine, headers, item).status_code == 200
    c.post("/api/brain/%s/config" % machine, json={"enabled": False})
    assert send(c, machine, headers, item).status_code == 409
    assert c.post("/ingest-brain/" + machine, json={"items": []}, headers=headers).status_code == 409


def test_malformed_items_are_refused_whole(remote):
    c, store, machine, headers = remote
    assert send(c, machine, headers, {"id": "x", "kind": "command", "observed": time.time()}).status_code == 400
    assert c.post("/ingest-brain/" + machine, json={"items": []}, headers=headers).status_code == 400
    assert c.post("/ingest-brain/" + machine, json=[1], headers=headers).status_code == 400


def test_the_first_inventory_is_a_baseline_and_later_ones_record_changes(remote):
    c, store, machine, headers = remote
    now = time.time()
    first = inventory(now - 7200, packages={"nginx": "1.0", "curl": "8.0"}, users={"alice": "uid 1000, /bin/bash"})
    assert send(c, machine, headers, first).json()["acknowledged"] == [first["id"]]
    assert c.get("/api/brain/changes").json()["changes"] == []
    second = inventory(now - 3600, packages={"nginx": "1.1", "curl": "8.0"}, users={"alice": "uid 1000, /bin/bash", "mallory": "uid 1001, /bin/sh"})
    send(c, machine, headers, second)
    changes = c.get("/api/brain/changes", params={"machine": machine}).json()["changes"]
    assert {(r["category"], r["action"], r["item"], r["before"], r["after"]) for r in changes} == {
        ("packages", "changed", "nginx", "1.0", "1.1"),
        ("users", "added", "mallory", "", "uid 1001, /bin/sh"),
    }
    # The same picture again, and a replay of an older one, add nothing.
    same = dict(second, id="inv-again", observed=now - 60)
    send(c, machine, headers, same)
    send(c, machine, headers, first)
    assert len(c.get("/api/brain/changes").json()["changes"]) == 2
    status = next(m for m in c.get("/api/brain").json()["machines"] if m["machine_id"] == machine)
    assert status["counts"]["packages"] == 2 and status["changes_week"] == 2
    assert status["inventory_observed"] == pytest.approx(now - 60)
    found = c.get("/api/brain/%s/inventory" % machine, params={"q": "ngin"}).json()
    assert [(i["item"], i["value"]) for i in found["items"]] == [("nginx", "1.1")]


def test_activity_is_searchable_by_project_machine_and_text(remote):
    c, store, machine, headers = remote
    other, _ = machine_source(c)
    c.post("/api/brain/%s/config" % other, json={"enabled": True})
    other_headers = {"Authorization": "Bearer " + c.post("/api/brain/%s/token" % other).json()["token"]}
    now = time.time()
    send(c, machine, headers,
         command(1, now - 300, "git commit -m 'checkout page'"),
         command(2, now - 200, "pytest tests/test_cart.py"),
         command(3, now - 100, "systemctl restart nginx", cwd="/etc/nginx", project=""))
    send(c, other, other_headers, command(1, now - 50, "git pull", cwd="/srv/shop", project="shop"))
    # Delivered twice: stored once.
    send(c, machine, headers, command(2, now - 200, "pytest tests/test_cart.py"))
    everything = c.get("/api/brain/activity").json()["commands"]
    assert [r["command"] for r in everything] == [
        "git pull", "systemctl restart nginx", "pytest tests/test_cart.py", "git commit -m 'checkout page'"]
    assert len(c.get("/api/brain/activity", params={"machine": machine}).json()["commands"]) == 3
    assert [r["command"] for r in c.get("/api/brain/activity", params={"q": "pytest"}).json()["commands"]] == ["pytest tests/test_cart.py"]
    # % and _ in a search are text, not wildcards.
    assert c.get("/api/brain/activity", params={"q": "%"}).json()["commands"] == []
    projects = c.get("/api/brain/projects").json()["projects"]
    shop = {p["machine_id"]: p for p in projects if p["label"] == "shop"}
    assert shop[machine]["commands"] == 2 and shop[other]["commands"] == 1
    assert any(p["label"] == "/etc/nginx" and not p["repository"] for p in projects)
    assert len(c.get("/api/brain/activity", params={"project": "/etc/nginx"}).json()["commands"]) == 1
    days = c.get("/api/brain/days", params={"machine": other}).json()["days"]
    assert [(d["label"], d["commands"]) for d in days] == [("shop", 1)]


def test_commands_are_refused_when_activity_is_turned_off_centrally(remote):
    c, store, machine, headers = remote
    c.post("/api/brain/%s/config" % machine, json={"activity": False})
    answer = send(c, machine, headers, command(1, time.time(), "ls")).json()
    assert answer["acknowledged"] == [] and answer["rejected"][0]["reason"] == "activity_disabled"
    assert c.get("/api/brain/activity").json()["commands"] == []


def test_only_the_local_machine_may_be_read_locally(remote):
    c, store, machine, headers = remote
    assert c.post("/api/brain/%s/config" % machine, json={"mode": "local"}).status_code == 400


def test_deleting_a_machine_takes_its_memory_with_it(remote):
    c, store, machine, headers = remote
    send(c, machine, headers, command(1, time.time(), "ls"), inventory(time.time() - 10, packages={"a": "1"}))
    from logsentinel.portal.machines import deletion_preview, erase_machine

    assert deletion_preview(store, machine)["counts"]["brain_commands"] == 1
    erase_machine(store, machine)
    with store.connect() as db:
        for table in ("brain_commands", "brain_snapshots", "brain_changes"):
            assert db.execute("SELECT count(*) FROM %s" % table).fetchone()[0] == 0
    assert store.meta("brain_token:" + machine) is None
    assert store.get("brain_config", "brain:" + machine) is None


def test_old_activity_expires_with_the_machine_retention(remote):
    c, store, machine, headers = remote
    c.post("/api/brain/%s/config" % machine, json={"retention_days": 2})
    now = time.time()
    send(c, machine, headers, command(1, now - 86400, "kept"))
    with store.connect() as db:
        db.execute("INSERT INTO brain_commands VALUES(?,?,?,?,?,?,?)", (machine, "old", now - 3 * 86400, "alice", "/", "", "gone"))
    assert c.app.state.brain.data.prune() == 1
    assert [r["command"] for r in c.get("/api/brain/activity").json()["commands"]] == ["kept"]


def test_question_terms_drop_filler_words():
    assert terms("¿En qué equipo trabajé en el proyecto shop con nginx?") == ["shop", "nginx"]
    assert terms("where did I install docker-compose") == ["install", "docker-compose"]


def test_a_question_sends_only_matching_records_and_can_be_previewed(remote, monkeypatch):
    c, store, machine, headers = remote
    now = time.time()
    send(c, machine, headers,
         inventory(now - 500, packages={"nginx": "1.1", "curl": "8.0"}),
         command(1, now - 300, "vim deploy.yml", cwd="/srv/alice/shop", project="shop"),
         command(2, now - 200, "ssh backup.example.invalid", cwd="/srv/alice", project=""))
    body = {"message": "what did I do with nginx and the shop deploy?", "days": 7}
    preview = c.post("/api/brain/context", json=body).json()
    payload = preview["payload"]
    assert [r["command"] for r in payload["commands"]] == ["vim deploy.yml"]
    assert payload["installed_matches"] == [dict(machine="A", category="packages", item="nginx", value="1.1")]
    assert payload["projects"][0]["machine"] == "A"
    sent = {}

    async def fake(self, payload, kind="analysis", **options):
        sent.update(payload=payload, kind=kind, system=options["system"])
        return {"answer": "You edited deploy.yml in shop on A."}

    monkeypatch.setattr(ReviewClient, "call", fake)
    answer = c.post("/api/brain/ask", json=dict(body, language="es"))
    assert answer.status_code == 200, answer.text
    assert answer.json()["answer"] == "You edited deploy.yml in shop on A."
    assert sent["payload"] == payload and sent["kind"] == "brain"
    assert sent["system"].endswith("Spanish.") and "untrusted" in sent["system"]


def test_a_question_context_stays_within_its_budget(remote):
    c, store, machine, headers = remote
    now = time.time()
    send(c, machine, headers, *[command(n, now - n, "make target-%d " % n + "x" * 400) for n in range(300)])
    payload = c.app.state.brain.context("make target", budget=6000)
    assert len(json.dumps(payload).encode()) <= 6200 and not payload["truncated"]
    assert payload["commands"] and payload["commands"][0]["command"].startswith("make target-0 ")


def test_a_journal_entry_becomes_a_redacted_record_with_the_journals_own_user(monkeypatch):
    monkeypatch.setattr(brain_collect, "user_name", lambda uid: "alice" if uid == "1000" else "?")
    record = brain_collect.activity_record({
        "MESSAGE": "curl -H 'Authorization: Bearer abcdefghijklmnop123456' https://example.invalid/x --password=hunter2secret",
        "LS_CWD": "/srv/alice/shop", "LS_PROJECT": "shop", "_UID": "1000",
        "__CURSOR": "s=1;i=2", "__REALTIME_TIMESTAMP": "1700000000000000",
        "LS_USER": "root",  # a field the writer chose is not who wrote it
    })
    assert record["user"] == "alice" and record["observed"] == 1700000000.0
    assert record["cwd"] == "/srv/alice/shop" and record["project"] == "shop"
    assert "abcdefghijklmnop123456" not in record["command"] and "hunter2secret" not in record["command"]
    assert brain_collect.activity_record({"MESSAGE": "", "__CURSOR": "c", "__REALTIME_TIMESTAMP": "1"}) is None
    assert brain_collect.activity_record({"MESSAGE": "ls", "__CURSOR": "c"}) is None


def test_reading_activity_follows_the_cursor_and_survives_a_lost_one(monkeypatch):
    calls = []

    def entry(n):
        return json.dumps({"MESSAGE": "cmd %d" % n, "_UID": "0", "__CURSOR": "c%d" % n, "__REALTIME_TIMESTAMP": str(n * 10**6)})

    def fake(arguments, timeout=30):
        calls.append(arguments)
        if "--after-cursor" in arguments:
            return None if arguments[-1] == "gone" else [entry(3), "not json", entry(4)]
        return [entry(1), entry(2)]

    monkeypatch.setattr(brain_collect, "run", fake)
    records, cursor = brain_collect.read_activity("")
    assert [r["command"] for r in records] == ["cmd 1", "cmd 2"] and cursor == "c2"
    records, cursor = brain_collect.read_activity("c2")
    assert [r["command"] for r in records] == ["cmd 3", "cmd 4"] and cursor == "c4"
    records, cursor = brain_collect.read_activity("gone")
    assert cursor == "c2" and "--since" in calls[-1]
    monkeypatch.setattr(brain_collect, "run", lambda *a, **k: None)
    with pytest.raises(OSError):
        brain_collect.read_activity("")


def test_an_inventory_names_the_readers_that_failed(monkeypatch):
    monkeypatch.setattr(brain_collect, "packages", lambda: {"nginx": "1.0"})
    monkeypatch.setattr(brain_collect, "services", lambda: None)
    monkeypatch.setattr(brain_collect, "ports", lambda: {})
    monkeypatch.setattr(brain_collect, "users", lambda: {"alice": "uid 1000, /bin/bash"})
    found = brain_collect.inventory(1000.0)
    assert found["errors"] == ["services"] and "services" not in found["data"]
    assert found["data"]["packages"] == {"nginx": "1.0"} and found["data"]["ports"] == {}
    assert brain_collect.inventory(2000.0)["digest"] == found["digest"]


def test_the_central_reads_its_own_machine_when_set_to_local(client, monkeypatch):
    c, store = client
    machine = c.post("/api/objects/machine", json={"name": "central", "kind": "local"}).json()["id"]
    assert c.post("/api/brain/%s/config" % machine, json={"enabled": True, "mode": "local"}).status_code == 200
    now = time.time()
    monkeypatch.setattr(brain_collect, "inventory", lambda moment: inventory(moment, packages={"nginx": "1.0"}))
    seen = []

    def activity(cursor):
        seen.append(cursor)
        return [command(len(seen), now, "ls")], "cursor-%d" % len(seen)

    monkeypatch.setattr(brain_collect, "read_activity", activity)
    brain = c.app.state.brain
    brain.tick(now)
    brain.tick(now + 1)  # not due yet
    brain.tick(now + 61)
    assert seen == ["", "cursor-1"]
    status = next(m for m in c.get("/api/brain").json()["machines"] if m["machine_id"] == machine)
    assert status["commands_total"] == 2 and status["counts"]["packages"] == 1 and status["error"] == ""

    def broken(cursor):
        raise OSError("Cannot read the journal")

    monkeypatch.setattr(brain_collect, "read_activity", broken)
    brain.tick(now + 200)
    assert "Cannot read the journal" in store.meta("brain_error:" + machine)


def test_the_hook_is_installed_once_and_removed_cleanly(tmp_path):
    (tmp_path / "etc/profile.d").mkdir(parents=True)
    bashrc = tmp_path / "etc/bash.bashrc"
    bashrc.write_text("# system bashrc\nalias ll='ls -l'")
    install_hook(tmp_path)
    install_hook(tmp_path)
    assert bashrc.read_text().count(MARK) == 1 and bashrc.read_text().startswith("# system bashrc\nalias ll='ls -l'\n")
    assert (tmp_path / "etc/logsentinel-activity.sh").read_text() == brain_collect.ACTIVITY_HOOK
    assert MARK in (tmp_path / "etc/profile.d/logsentinel-activity.sh").read_text()
    assert not (tmp_path / "etc/zsh").exists()  # nothing invented for a shell that is not there
    remove_hook(tmp_path)
    assert bashrc.read_text() == "# system bashrc\nalias ll='ls -l'\n"
    assert not (tmp_path / "etc/logsentinel-activity.sh").exists()
    assert remove_hook(tmp_path) == ["Nothing to remove"]


def test_recorded_commands_never_enter_the_log_capture(client):
    """The hook writes to the journal the log sources also read; those entries
    belong to the brain alone."""
    from logsentinel.collectors.journald import JournaldCollector
    from logsentinel.config import JournaldSourceConfig

    c, store = client
    machine, source = machine_source(c)
    token = c.post("/api/sources/%s/token" % source).json()["token"]
    typed = json.dumps({"MESSAGE": "mysql -psecretword", "SYSLOG_IDENTIFIER": "logsentinel-activity", "__CURSOR": "c1", "__REALTIME_TIMESTAMP": "1700000000000000"})
    logged = json.dumps({"MESSAGE": "Started nginx", "SYSLOG_IDENTIFIER": "systemd", "__CURSOR": "c2", "__REALTIME_TIMESTAMP": "1700000001000000"})
    parse = JournaldCollector(JournaldSourceConfig())._parse_json_line
    assert parse(typed) is None and parse(logged).message == "Started nginx"
    # An older sender still forwards them: acknowledged so it moves on, not stored.
    answer = c.post(
        "/ingest/" + source,
        json={"format": "journal", "events": [{"id": "a", "raw": typed}, {"id": "b", "raw": logged}]},
        headers={"Authorization": "Bearer " + token},
    )
    assert answer.status_code == 200, answer.text
    assert answer.json()["acknowledged"] == ["a", "b"] and answer.json()["accepted"] == 1
    assert [e["message"] for e in store.events(source_id=source)] == ["Started nginx"]
    only = c.post(
        "/ingest/" + source,
        json={"format": "journal", "events": [{"id": "c", "raw": typed}]},
        headers={"Authorization": "Bearer " + token},
    )
    assert only.status_code == 200 and only.json()["accepted"] == 0
    assert len(store.events(source_id=source)) == 1


@pytest.mark.asyncio
async def test_the_remote_sender_delivers_through_its_spool_and_survives_a_lost_answer(tmp_path, monkeypatch):
    import httpx
    from logsentinel.portal.app import create_app
    from logsentinel.portal.brain_data import BrainConfig
    from logsentinel.portal.brain_forward import forward_brain
    from logsentinel.portal.models import Machine
    from logsentinel.portal.store import Store

    app = create_app(tmp_path / "central", background=False)
    store, brain = app.state.store, app.state.brain
    machine = store.put("machine", Machine(name="Remote").model_dump())
    brain.data.configure(machine, BrainConfig(enabled=True))
    store.set_meta("brain_token:" + machine, hashlib.sha256(b"synthetic").hexdigest())
    now = time.time()
    # A real host has thousands of packages: the inventory must fit the spool and the request.
    big = {"package-%05d" % n: "1.%d-synthetic" % n for n in range(6000)}
    monkeypatch.setattr(brain_collect, "inventory", lambda moment: inventory(moment, packages=big))
    reads = []

    def activity(cursor):
        reads.append(cursor)
        return ([command("r%d" % len(reads), now - 5, "make test")], "cursor-%d" % len(reads))

    monkeypatch.setattr(brain_collect, "read_activity", activity)
    original = httpx.AsyncClient
    transport = httpx.ASGITransport(app=app)

    class LostAnswer(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            await transport.handle_async_request(request)
            raise httpx.ReadTimeout("answer lost after commit")

    def use(chosen):
        monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(transport=chosen, **{k: v for k, v in kw.items() if k != "transport"}))

    spool = tmp_path / "spool"
    use(LostAnswer())
    with pytest.raises(RuntimeError, match="retained"):
        await forward_brain("http://localhost", machine, "synthetic", spool, once=True)
    assert len(Store(spool).events(status="pending")) == 2  # kept: the sender heard nothing
    assert brain.data.status(machine)["commands_total"] == 1  # though the central stored it
    use(transport)
    await forward_brain("http://localhost", machine, "synthetic", spool, once=True)
    assert not Store(spool).events(status="pending")
    status = brain.data.status(machine)
    # Redelivery stored nothing twice; the second run added its own command only.
    assert status["commands_total"] == 2 and status["counts"]["packages"] == 6000
    assert reads == ["", "cursor-1"]
    assert brain.data.changes(machine) == []  # one inventory a day, not one per run
    with pytest.raises(ValueError, match="another receiver"):
        await forward_brain("http://localhost", "other", "synthetic", spool, once=True)
    with pytest.raises(RuntimeError, match="retained"):
        await forward_brain("http://localhost", machine, "wrong-token", tmp_path / "second", once=True)


def test_a_question_reaches_the_model_redacted_and_is_billed_as_its_own_kind(remote, monkeypatch):
    import httpx

    c, store, machine, headers = remote
    cfg = store.settings()
    cfg.llm.provider, cfg.llm.base_url, cfg.llm.model = "openai", "http://localhost:9/v1", "synthetic"
    store.set_meta("settings", cfg.model_dump_json())
    send(c, machine, headers, command(1, time.time() - 60, "deploy --token=abcdefghijklmnop1234567890 shop"))
    bodies = []

    def handler(request):
        bodies.append(request.content.decode())
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps({"answer": "You deployed shop on A."})}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 9},
        })

    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(**dict(kw, transport=httpx.MockTransport(handler))))
    answer = c.post("/api/brain/ask", json={"message": "when did I deploy shop?"})
    assert answer.status_code == 200, answer.text
    assert answer.json()["answer"] == "You deployed shop on A."
    sent = bodies[-1]
    assert "deploy --token=" in sent and "abcdefghijklmnop1234567890" not in sent
    assert "untrusted" in sent
    assert [u["kind"] for u in store.rows("usage", 1)] == ["brain"]


def note(n, observed, text, agent="claude", project="shop", cwd="/srv/alice/shop", entry=""):
    return dict(id="note-%s" % n, entry=entry, kind="note", observed=observed, user="alice", cwd=cwd, project=project, agent=agent, text=text)


def test_diary_notes_are_kept_searched_and_one_per_session(remote):
    c, store, machine, headers = remote
    now = time.time()
    c.post("/api/brain/%s/config" % machine, json={"activity": False})  # notes do not depend on typed commands
    answer = send(c, machine, headers,
                  note("s1", now - 600, "Pedido: fix checkout · Resultado: started"),
                  note("s2", now - 500, "Refactored the cart tests", agent="codex"))
    assert answer.json()["acknowledged"] == ["note-s1", "note-s2"]
    # The same session writes again at each turn: the latest stands, an older replay does not.
    send(c, machine, headers, note("s1", now - 100, "Pedido: fix checkout · Resultado: fixed and tested"))
    send(c, machine, headers, note("s1", now - 900, "stale"))
    notes = c.get("/api/brain/notes").json()["notes"]
    assert [(n["agent"], n["text"]) for n in notes] == [
        ("claude", "Pedido: fix checkout · Resultado: fixed and tested"),
        ("codex", "Refactored the cart tests"),
    ]
    assert [n["agent"] for n in c.get("/api/brain/notes", params={"q": "codex"}).json()["notes"]] == ["codex"]
    assert len(c.get("/api/brain/notes", params={"project": "shop", "machine": machine}).json()["notes"]) == 2
    payload = c.post("/api/brain/context", json={"message": "what happened with checkout?"}).json()["payload"]
    assert [n["note"] for n in payload["agent_notes"]] == ["Pedido: fix checkout · Resultado: fixed and tested"]
    assert payload["agent_notes"][0]["machine"] == "A" and payload["agent_notes"][0]["agent"] == "claude"
    from logsentinel.portal.machines import erase_machine

    erase_machine(store, machine)
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM brain_notes").fetchone()[0] == 0


def test_a_note_in_the_journal_becomes_one_record_per_session(monkeypatch):
    monkeypatch.setattr(brain_collect, "user_name", lambda uid: "alice")

    def entry(cursor, session, text="did things --password=hunter2secret"):
        return {"MESSAGE": text, "LS_KIND": "note", "LS_AGENT": "claude", "LS_SESSION": session,
                "LS_CWD": "/srv/work/shop", "LS_PROJECT": "shop", "_UID": "1000",
                "__CURSOR": cursor, "__REALTIME_TIMESTAMP": "1700000000000000"}

    first, second, other, loose = (brain_collect.activity_record(e) for e in (
        entry("c1", "abc"), entry("c2", "abc"), entry("c3", "xyz"), entry("c4", "")))
    assert first["kind"] == "note" and first["agent"] == "claude" and "hunter2secret" not in first["text"]
    assert first["id"] == second["id"] != other["id"] and first["entry"] != second["entry"]
    assert loose["id"] == "note-" + loose["entry"]  # no session: every note stands alone


def test_writing_a_note_uses_the_journal_with_project_and_session(tmp_path, monkeypatch):
    (tmp_path / "shop/.git").mkdir(parents=True)
    work = tmp_path / "shop/src"
    work.mkdir()
    sent = {}

    def fake(arguments, **options):
        sent.update(arguments=arguments, body=options["input"])

        class Done:
            returncode, stderr = 0, ""

        return Done()

    monkeypatch.setattr(brain_collect.subprocess, "run", fake)
    brain_collect.write_note("first line\n\n second line ", "claude!", work, "sess 1")
    fields = dict(line.split("=", 1) for line in sent["body"].splitlines())
    assert sent["arguments"] == ["logger", "--journald"]
    assert fields["MESSAGE"] == "first line · second line" and fields["LS_KIND"] == "note"
    assert fields["LS_AGENT"] == "claude" and fields["LS_SESSION"] == "sess1"
    assert fields["LS_PROJECT"] == "shop" and fields["LS_CWD"] == str(work)
    assert fields["SYSLOG_IDENTIFIER"] == "logsentinel-activity"
    with pytest.raises(ValueError):
        brain_collect.write_note("  \n ", "claude")


def test_a_transcript_is_summarised_without_a_model(tmp_path):
    path = tmp_path / "session.jsonl"
    lines = [
        {"type": "user", "message": {"role": "user", "content": "<system-reminder>ignored</system-reminder>"}},
        {"type": "user", "message": {"role": "user", "content": "Fix the checkout bug\nin the cart"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash"}, {"type": "text", "text": "Looking."}]}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "output"}]}},
        {"type": "assistant", "isSidechain": True, "message": {"role": "assistant", "content": "subagent chatter"}},
        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Fixed: the total ignored discounts. " + "x" * 600}]}},
    ]
    path.write_text("not json\n" + "\n".join(json.dumps(l) for l in lines))
    text = brain_collect.transcript_note(path)
    asked, answered = text.split("\n")
    assert asked == "Pedido: Fix the checkout bug in the cart"
    assert answered.startswith("Resultado: Fixed: the total ignored discounts.") and answered.endswith("…") and len(answered) < 420
    assert brain_collect.transcript_note(tmp_path / "missing.jsonl") == ""
    (tmp_path / "empty.jsonl").write_text("")
    assert brain_collect.transcript_note(tmp_path / "empty.jsonl") == ""


def test_the_hook_command_never_fails_the_agent(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from logsentinel.cli import app

    written = []
    monkeypatch.setattr(brain_collect, "write_note", lambda *a: written.append(a))
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(json.dumps({"type": "user", "message": {"content": "do it"}}))
    event = json.dumps({"transcript_path": str(transcript), "cwd": "/srv/shop", "session_id": "s-1"})
    runner = CliRunner()
    assert runner.invoke(app, ["brain-note", "--agent", "claude", "--from-hook"], input=event).exit_code == 0
    assert written == [("Pedido: do it", "claude", "/srv/shop", "s-1")]
    for broken in ("", "not json", "[]", json.dumps({"transcript_path": "/nonexistent"})):
        assert runner.invoke(app, ["brain-note", "--from-hook"], input=broken).exit_code == 0
    assert len(written) == 1
    assert runner.invoke(app, ["brain-note", "--agent", "codex", "done the thing"]).exit_code == 0
    assert written[-1][:2] == ("done the thing", "codex")


def test_the_installer_sets_up_a_confined_service_and_removes_it(tmp_path):
    from logsentinel.portal import brain_install

    ran = []
    accounts = set()

    def run(arguments):
        ran.append(arguments)
        if arguments[0] == "id" and arguments[1] not in accounts:
            raise OSError("no such user")
        if arguments[0] == "useradd":
            accounts.add(arguments[-1])
        return ""

    sender = tmp_path / "var/lib/logsentinel-client/logs"
    sender.mkdir(parents=True)
    (sender / "receiver-ca.pem").write_text("synthetic authority")
    (tmp_path / "etc").mkdir()
    (tmp_path / "etc/bash.bashrc").write_text("# bashrc\n")
    runtime = tmp_path / "opt/logsentinel-client/runtime-abc/bin/python"
    token = "t" * 43
    done = brain_install.install(
        "https://127.0.0.1:18767", "0123abcd", token, hook=True, root=tmp_path, run=run, executable=runtime
    )
    unit = (tmp_path / "etc/systemd/system/logsentinel-brain.service").read_text()
    assert "User=ls-brain" in unit and "SupplementaryGroups=systemd-journal" in unit
    assert "ProtectSystem=strict" in unit and "CapabilityBoundingSet=\n" in unit
    assert "brain-forward --receiver https://127.0.0.1:18767 --machine-id 0123abcd" in unit
    # A client runtime moves with every upgrade: the unit finds the newest when it starts.
    assert "ls -1dt " + str(tmp_path / "opt/logsentinel-client") + "/runtime-*/" in unit
    assert token not in unit  # the token is not in a world-readable file
    env = tmp_path / "etc/logsentinel-clients/brain.env"
    assert env.read_text() == "LOGSENTINEL_BRAIN_TOKEN=" + token + "\n" and env.stat().st_mode & 0o777 == 0o600
    spool = tmp_path / "var/lib/logsentinel-client/brain"
    assert (spool / "receiver-ca.pem").read_text() == "synthetic authority" and spool.stat().st_mode & 0o777 == 0o700
    assert ["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", "ls-brain"] in ran
    assert ran[-2:] == [["systemctl", "enable", "logsentinel-brain.service"], ["systemctl", "restart", "logsentinel-brain.service"]]
    assert (tmp_path / "etc/logsentinel-activity.sh").exists() and any("ls-brain" in line for line in done)
    # Again: the account is not created twice and the token can be replaced.
    ran.clear()
    brain_install.install("https://127.0.0.1:18767", "0123abcd", "u" * 43, root=tmp_path, run=run, executable=runtime, activity=False)
    assert not any(a[0] == "useradd" for a in ran) and "u" * 43 in env.read_text()
    assert "--no-activity" in (tmp_path / "etc/systemd/system/logsentinel-brain.service").read_text()
    # Outside a client runtime the program next to the interpreter is named as it is.
    assert brain_install.launcher(tmp_path, tmp_path / "srv/venv/bin/python") == str(tmp_path / "srv/venv/bin/logsentinel")
    brain_install.remove(tmp_path, run, purge=True)
    assert not env.exists() and not spool.exists() and not (tmp_path / "etc/logsentinel-activity.sh").exists()
    assert (tmp_path / "etc/bash.bashrc").read_text() == "# bashrc\n"
    assert brain_install.remove(tmp_path, lambda a: (_ for _ in ()).throw(OSError("gone"))) == ["Nothing to remove"]


@pytest.mark.parametrize("receiver,machine,token", [
    ("http://central:8767", "abc", "t" * 43),
    ("https://central:8767; rm -rf /", "abc", "t" * 43),
    ("https://central:8767", "abc def", "t" * 43),
    ("https://central:8767", "abc", "short"),
])
def test_the_installer_refuses_what_would_not_be_safe_in_a_unit(tmp_path, receiver, machine, token):
    from logsentinel.portal import brain_install

    with pytest.raises(ValueError):
        brain_install.install(receiver, machine, token, root=tmp_path, run=lambda a: "")
    assert not (tmp_path / "etc").exists()


def test_a_brain_enabled_with_nothing_reporting_is_noticed(remote, monkeypatch):
    from logsentinel.portal.health import NEVER_CONNECTED_SECONDS

    c, store, machine, headers = remote
    health = c.app.state.health
    clock = [time.time()]
    monkeypatch.setattr(time, "time", lambda: clock[0])

    def bad():
        return next(k for k in health.conditions() if k["key"] == "brain:" + machine)["bad"]

    assert not bad()
    clock[0] += NEVER_CONNECTED_SECONDS + 1
    assert bad()  # enabled an hour ago, never a report
    send(c, machine, headers, inventory(clock[0] - 5, packages={"a": "1"}))
    assert not bad()
    clock[0] += 86400 * 2
    assert not bad()  # one missed inventory is not silence yet
    clock[0] += 86400
    assert bad()
    from logsentinel.portal.brain_data import BrainConfig

    c.app.state.brain.data.configure(machine, BrainConfig(enabled=False))  # the session aged with the clock
    assert not any(k["key"] == "brain:" + machine for k in health.conditions())
