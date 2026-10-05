"""One journal record bigger than the capture batch must not stop the journal source."""

import json

from logsentinel.portal.collect import MAX_LINE, Collector
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store


def journal_source(store, **extra):
    machine = store.put("machine", Machine(name="A").model_dump())
    return dict(Source(machine_id=machine, name="journal", kind="journald", enabled=True, history=True, **extra).model_dump(), id="j")


def output(records):
    payload = b"".join(json.dumps(r).encode() + b"\n" for r in records)
    calls = []

    def read(command, limit):
        calls.append(limit)
        return payload[:limit], len(payload) >= limit

    return read, calls


def test_a_record_bigger_than_the_batch_is_cut_and_the_cursor_moves_on(tmp_path, monkeypatch):
    store = Store(tmp_path)
    source = journal_source(store, max_batch_bytes=4096)
    read, calls = output([
        {"__CURSOR": "c1", "MESSAGE": "x" * 20_000, "SYSLOG_IDENTIFIER": "app"},
        {"__CURSOR": "c2", "MESSAGE": "after", "SYSLOG_IDENTIFIER": "app"},
    ])
    monkeypatch.setattr("logsentinel.portal.collect.read_journal", read)
    collector = Collector(store)
    assert collector.journal(source) >= 1
    first = store.events(limit=10)[0]
    assert first["message"].startswith("xxx") and len(first["raw"].encode()) <= MAX_LINE
    assert store.cursor("j", "journal")["cursor"] in ("c1", "c2")
    collector.journal(source)
    assert [e["message"] for e in store.events(limit=10)][-1] == "after"
    assert store.cursor("j", "journal")["cursor"] == "c2"
    assert max(calls) > 4096, "the record was read again with more room"


def test_a_record_that_is_too_big_even_for_the_retry_is_cut_rather_than_fatal(tmp_path, monkeypatch):
    store = Store(tmp_path)
    source = journal_source(store, max_batch_bytes=4096)
    read, calls = output([{"__CURSOR": "big", "MESSAGE": "y" * 600_000}, {"__CURSOR": "c2", "MESSAGE": "after"}])
    monkeypatch.setattr("logsentinel.portal.collect.read_journal", read)
    collector = Collector(store)
    collector.journal(source)
    collector.journal(source)
    messages = [e["message"] for e in store.events(limit=10)]
    assert messages[-1] == "after"
    assert all(len(e["raw"].encode()) <= MAX_LINE for e in store.events(limit=10))


def test_an_ordinary_journal_poll_reads_once(tmp_path, monkeypatch):
    store = Store(tmp_path)
    source = journal_source(store)
    read, calls = output([{"__CURSOR": "c1", "MESSAGE": "one"}, {"__CURSOR": "c2", "MESSAGE": "two"}])
    monkeypatch.setattr("logsentinel.portal.collect.read_journal", read)
    assert Collector(store).journal(source) == 2
    assert len(calls) == 1
