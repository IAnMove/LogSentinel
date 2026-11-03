"""A vanished journal position is recorded loudly and capture resumes."""

import json
import time

from helpers import machine_source
from logsentinel.portal.collect import Collector, JOURNAL_GAP_LOOKBACK, cursor_time
from logsentinel.portal.journal_stream import JournalReadError
from logsentinel.portal.models import Source
from logsentinel.portal.store import Store


def journald_source(store):
    return dict(
        Source(name="journal", machine_id="m", kind="journald", enabled=True).model_dump(),
        id="j",
    )


def gaps(store):
    with store.connect() as db:
        row = db.execute("SELECT value FROM metrics WHERE source_id='j' AND key='journal_gaps'").fetchone()
    return row[0] if row else 0


def lost_cursor(seconds_ago):
    return "s=a;i=1;b=b;m=1;t=%x;x=1" % int((time.time() - seconds_ago) * 1e6)


def record(cursor, text="after the gap"):
    return json.dumps(dict(__CURSOR=cursor, MESSAGE=text)).encode() + b"\n"


def test_cursor_time_reads_the_t_field():
    assert abs(cursor_time(lost_cursor(100)) - (time.time() - 100)) < 2
    assert cursor_time("garbage") is None and cursor_time("t=zz") is None


def test_lost_cursor_resumes_from_its_time_and_records_the_gap(tmp_path, monkeypatch):
    store = Store(tmp_path)
    source = journald_source(store)
    lost = lost_cursor(3600)
    store.ingest(source, [], "journal", {"cursor": lost})
    commands = []

    def fake(cmd, limit):
        commands.append(cmd)
        if "--cursor" in cmd:  # journalctl seeks near it and returns another record
            return record("new"), False
        return record("new") + record("newer", "second"), False

    monkeypatch.setattr("logsentinel.portal.collect.read_journal", fake)
    assert Collector(store).poll(source, True) == 2
    assert store.cursor("j", "journal") == {"cursor": "newer"}
    since = next(c[c.index("--since") + 1] for c in commands if "--since" in c)
    assert abs(float(since[1:]) - cursor_time(lost)) < 1  # from the lost entry, not later
    gap = json.loads(store.meta("journal_gap:j"))
    assert gap["lost_cursor"] == lost and not gap["lookback_capped"]
    assert gap["resumed_from"] == float(since[1:]) or abs(gap["resumed_from"] - float(since[1:])) < 1e-3
    assert gaps(store) == 1


def test_seek_failure_is_treated_as_the_same_gap(tmp_path, monkeypatch):
    store = Store(tmp_path)
    source = journald_source(store)
    store.ingest(source, [], "journal", {"cursor": lost_cursor(60)})

    def fake(cmd, limit):
        if "--cursor" in cmd:
            raise JournalReadError("journal_retention_gap", 1)
        return record("fresh"), False

    monkeypatch.setattr("logsentinel.portal.collect.read_journal", fake)
    assert Collector(store).poll(source, True) == 1
    assert store.cursor("j", "journal") == {"cursor": "fresh"}
    assert store.meta("journal_gap:j")


def test_old_gap_is_capped_so_a_long_outage_does_not_flood(tmp_path, monkeypatch):
    store = Store(tmp_path)
    source = journald_source(store)
    store.ingest(source, [], "journal", {"cursor": lost_cursor(21 * 86400)})
    seen = []

    def fake(cmd, limit):
        seen.append(cmd)
        return (record("x"), False) if "--since" in cmd else (record("y"), False)

    monkeypatch.setattr("logsentinel.portal.collect.read_journal", fake)
    Collector(store).poll(source, True)
    since = float(next(c[c.index("--since") + 1] for c in seen if "--since" in c)[1:])
    assert abs(since - (time.time() - JOURNAL_GAP_LOOKBACK)) < 5
    assert json.loads(store.meta("journal_gap:j"))["lookback_capped"] is True


def test_quiet_journal_after_a_gap_counts_it_once(tmp_path, monkeypatch):
    store = Store(tmp_path)
    source = journald_source(store)
    lost = lost_cursor(60)
    store.ingest(source, [], "journal", {"cursor": lost})
    monkeypatch.setattr(
        "logsentinel.portal.collect.read_journal",
        lambda cmd, limit: (record("other"), False) if "--cursor" in cmd else (b"", False),
    )
    for _ in range(3):
        assert Collector(store).poll(source, True) == 0
    assert store.cursor("j", "journal") == {"cursor": lost}
    assert gaps(store) == 1


def test_intact_cursor_does_not_record_anything(tmp_path, monkeypatch):
    store = Store(tmp_path)
    source = journald_source(store)
    store.ingest(source, [], "journal", {"cursor": "same"})
    monkeypatch.setattr(
        "logsentinel.portal.collect.read_journal",
        lambda cmd, limit: (record("same") + record("next"), False),
    )
    assert Collector(store).poll(source, True) == 1
    assert store.meta("journal_gap:j") is None


def test_gap_becomes_a_health_condition_that_expires(client):
    c, store = client
    machine, _ = machine_source(c)
    sid = store.put("source", Source(name="System logs", kind="journald", enabled=True, machine_id=machine).model_dump())
    health = c.app.state.health

    def check():
        return next((x for x in health.conditions() if x["key"] == "journal_gap:" + sid), None)

    assert check() is None
    now = time.time()
    store.set_meta("journal_gap:" + sid, json.dumps(dict(detected=now, lost_cursor="x", lost_cursor_time=now - 600, resumed_from=now - 600, lookback_capped=False)))
    gap = check()
    assert gap["bad"] and gap["title"] == "Journal coverage gap" and gap["detail"]["capture_resumed_from"]
    store.set_meta("journal_gap:" + sid, json.dumps(dict(detected=now - 2 * 86400, lost_cursor="x")))
    assert not check()["bad"]
