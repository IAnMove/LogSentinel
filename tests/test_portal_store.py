import gzip
from pathlib import Path
import pytest
from logsentinel.portal.store import Store
from logsentinel.portal.collect import Collector
from logsentinel.portal.models import Machine, Source


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / "data")
    machine = store.put("machine", Machine(name="A").model_dump())
    source = dict(
        Source(
            machine_id=machine,
            name="auth",
            path=str(tmp_path / "auth.log"),
            enabled=True,
            history=True,
        ).model_dump(),
        id="s",
    )
    return store, source, Path(source["path"])


def test_segment_cursor_and_dedup_survive_restart(setup):
    store, source, path = setup
    path.write_text("line one\nline one\npartial")
    c = Collector(store)
    assert c.file(source, path) == 2
    assert c.file(source, path) == 0
    with path.open("a") as f:
        f.write(" completed\n")
    store = Store(store.directory)
    assert Collector(store).file(source, path) == 1
    assert [e["message"] for e in store.events()] == [
        "line one",
        "line one",
        "partial completed",
    ]
    assert store.stats()["segments"]["compressed"] > 0


def test_gzip_stability_and_import_idempotency(setup, monkeypatch):
    store, source, path = setup
    path = path.with_suffix(".log.gz")
    path.write_bytes(gzip.compress(b"one\ntwo\n"))

    def refuse_slurp(*_args, **_kwargs):
        raise AssertionError("compressed sources must be hashed in chunks")

    monkeypatch.setattr(type(path), "read_bytes", refuse_slurp)
    c = Collector(store)
    assert c.file(source, path) == 0
    assert c.file(source, path) == 2
    assert c.file(source, path) == 0
    assert len(store.events()) == 2
    assert store.cursor("s", str(path))["digest"]


def test_gzip_expanded_limit_stops_without_stalling(setup, monkeypatch):
    import logsentinel.portal.collect as collect

    store, source, path = setup
    path = path.with_suffix(".log.gz")
    path.write_bytes(gzip.compress(b"one\ntwo\nthree\n"))
    monkeypatch.setattr(collect, "MAX_EXPANDED_BYTES", 8)
    c = Collector(store)
    assert c.file(source, path) == 0
    first = c.file(source, path)
    assert first >= 1
    cursor = store.cursor("s", str(path))
    assert cursor["done"] is True
    assert c.file(source, path) == 0
    assert len(store.events()) == first


def test_transaction_failure_does_not_advance_cursor(setup, monkeypatch):
    store, source, path = setup
    path.write_text("one\n")
    monkeypatch.setattr(store, "size", lambda: 10**12)
    with pytest.raises(OSError):
        Collector(store).file(source, path)
    assert store.cursor("s", str(path)) is None
    assert store.events() == []


def test_backup_includes_compressed_evidence(setup, tmp_path):
    store, source, path = setup
    path.write_text("one\n")
    Collector(store).file(source, path)
    dest = tmp_path / "restored"
    dest.mkdir()
    store.backup(dest / "sentinel.db")
    assert Store(dest).events()[0]["message"] == "one"


def test_machines_do_not_merge_origins(setup):
    store, source, path = setup
    e = {"message": "same", "origin": "0"}
    store.ingest(source, [e])
    store.ingest(dict(source, id="other", machine_id="B"), [e])
    assert len(store.events()) == 2


def test_sender_cleanup_preserves_checkpoint_and_partial_segments(setup):
    store, source, path = setup
    path.write_text("one\ntwo\n")
    Collector(store).file(source, path)
    rows = store.events()
    store.mark([rows[0]["id"]], "sent")
    assert store.discard_sent() == 0
    store.mark([rows[1]["id"]], "sent")
    assert store.discard_sent() == 1
    assert store.events() == []
    assert Collector(store).file(source, path) == 0
    with path.open("a") as f:
        f.write("three\n")
    assert Collector(store).file(source, path) == 1


def test_retention_reclaims_segments_without_changing_cursor(setup):
    store, source, path = setup
    path.write_text("one\n")
    Collector(store).file(source, path)
    with store.connect() as db:
        db.execute("UPDATE segments SET created=0")
    assert store.prune() == 1
    assert store.events() == []
    assert Collector(store).file(source, path) == 0


def test_open_rotated_descriptor_keeps_late_writes(setup):
    store, source, path = setup
    path.write_text("first\n")
    collector = Collector(store)
    try:
        assert collector.poll(source) == 1
        with path.open("a") as writer:
            rotated = path.with_suffix(".old")
            path.rename(rotated)
            path.write_text("new file\n")
            assert collector.poll(source) == 1
            writer.write("late old writer\n")
            writer.flush()
            rotated.unlink()
            assert collector.poll(source) == 1
        assert [e["message"] for e in store.events()] == [
            "first",
            "new file",
            "late old writer",
        ]
        assert collector.poll(source) == 0
    finally:
        collector.close()


def _journal_source(store):
    machine = store.objects("machine")[0]["id"]
    return dict(
        Source(
            machine_id=machine,
            name="journal",
            kind="journald",
            enabled=True,
            history=True,
        ).model_dump(),
        id="journal",
    )


def _journalctl_output(payload):
    return lambda command, limit: (payload[:limit], len(payload) >= limit)


def test_malformed_journal_line_does_not_stall_the_cursor(setup, monkeypatch):
    store, _, _ = setup
    source = _journal_source(store)
    good = (
        b'{"MESSAGE":"first","__CURSOR":"c1","SYSLOG_IDENTIFIER":"sshd"}\n'
        b"this is not json\n"
        b'{"MESSAGE":"second","__CURSOR":"c2","SYSLOG_IDENTIFIER":"sshd"}\n'
        b"[1,2,3]\n"
        b'{"MESSAGE":"third","__CURSOR":"c3","SYSLOG_IDENTIFIER":"sshd"}\n'
    )
    monkeypatch.setattr("logsentinel.portal.collect.read_journal", _journalctl_output(good))
    collector = Collector(store)
    assert collector.journal(source) == 3
    assert [e["message"] for e in store.events()] == ["first", "second", "third"]
    assert store.cursor("journal", "journal")["cursor"] == "c3"
    with store.connect() as db:
        skipped = db.execute(
            "SELECT value FROM metrics WHERE source_id=? AND key='journal_skipped'",
            ("journal",),
        ).fetchone()
    assert skipped[0] == 2

    monkeypatch.setattr(
        "logsentinel.portal.collect.read_journal",
        _journalctl_output(b'{"not":"a log line"}\nnot-json\n'),
    )
    assert collector.journal(source) == 0
    assert store.cursor("journal", "journal")["cursor"] == "c3"
    assert [e["message"] for e in store.events()] == ["first", "second", "third"]


def test_folder_cannot_ingest_sensitive_files_added_after_configuration(setup):
    store, source, path = setup
    folder = path.parent / "logs"
    folder.mkdir()
    source.update(kind="folder", path=str(folder), pattern="*")
    collector = Collector(store)
    try:
        (folder / "app.log").write_text("ordinary log\n")
        assert collector.poll(source) == 1
        (folder / "id_ed25519").write_text("synthetic private data\n")
        (folder / "shadow.gz").write_bytes(gzip.compress(b"synthetic password data\n"))
        (folder / "other.log").write_text("another log\n")
        assert collector.poll(source) == 1
        assert {e["message"] for e in store.events()} == {"ordinary log", "another log"}
        assert store.cursor(source["id"], str(folder / "id_ed25519")) is None
    finally:
        collector.close()


def test_opened_file_target_is_checked_after_symlink_swap(setup, monkeypatch):
    import os
    from logsentinel.portal.source_paths import open_source, UnsafeSourcePath

    store, source, path = setup
    path.write_text("normal log\n")
    secret = path.parent / "id_rsa"
    secret.write_text("synthetic private data\n")
    original = os.open

    def swapped(target, flags, *args, **kwargs):
        if Path(target) == path:
            path.unlink()
            path.symlink_to(secret)
        return original(target, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swapped)
    with pytest.raises(UnsafeSourcePath):
        open_source(path, store.directory)
    assert not store.events()


def test_runtime_guard_rejects_data_directory_alias(setup):
    from logsentinel.portal.source_paths import UnsafeSourcePath

    store, source, path = setup
    private = store.directory / "innocent.log"
    private.write_text("synthetic private data\n")
    path.symlink_to(private)
    with pytest.raises(UnsafeSourcePath):
        Collector(store).file(source, path)
    assert not store.events()


def test_key_file_is_restored_when_database_commit_fails(tmp_path, monkeypatch):
    from contextlib import contextmanager
    import sqlite3

    store = Store(tmp_path)
    store.write_access_key()
    previous = store.meta("admin_token")
    connect = store.connect

    @contextmanager
    def failed_commit():
        with connect() as db:
            yield db
            raise sqlite3.OperationalError("synthetic commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(store, "connect", failed_commit)
        with pytest.raises(sqlite3.OperationalError):
            store.rotate_admin_token()
    assert store.meta("admin_token") == previous
    assert store.meta("retired_admin_tokens") is None
    assert (tmp_path / "access-key.txt").read_text().strip() == previous
    assert not list(tmp_path.glob(".access-key-*"))
    assert not store.rows("audit")


def test_access_key_write_replaces_symlink_without_touching_target(tmp_path):
    store = Store(tmp_path / "data")
    target = tmp_path / "unrelated"
    target.write_text("unchanged")
    key = store.directory / "access-key.txt"
    key.symlink_to(target)
    store.write_access_key()
    assert not key.is_symlink()
    assert key.stat().st_mode & 0o777 == 0o600
    assert target.read_text() == "unchanged"


def test_concurrent_rotations_keep_file_database_and_retirements_consistent(tmp_path):
    import json
    from concurrent.futures import ThreadPoolExecutor

    stores = [Store(tmp_path), Store(tmp_path)]
    previous = stores[0].meta("admin_token")
    with ThreadPoolExecutor(max_workers=2) as workers:
        tokens = list(workers.map(lambda store: store.rotate_admin_token(), stores))
    active = stores[0].meta("admin_token")
    assert active in tokens
    assert (tmp_path / "access-key.txt").read_text().strip() == active
    assert set(json.loads(stores[0].meta("retired_admin_tokens"))) == {previous, *tokens} - {active}


def test_segment_cache_reuses_verified_data_without_hiding_corruption(tmp_path, monkeypatch):
    import gzip
    import json
    import pytest
    from logsentinel.portal.store import Store
    store = Store(tmp_path)
    store.ingest(dict(id="s", machine_id="m"), [dict(origin="1", message="message", metadata=dict(x=1))])
    actual = gzip.decompress
    calls = []
    def decompress(data):
        calls.append(1)
        return actual(data)
    monkeypatch.setattr(gzip, "decompress", decompress)
    first = store.events()[0]
    first["metadata"]["x"] = 99
    assert store.events()[0]["metadata"]["x"] == 1
    assert len(calls) == 1
    with store.connect() as db:
        db.execute("UPDATE segments SET data=?", (gzip.compress(json.dumps([dict(message="tampered")]).encode()),))
    with pytest.raises(ValueError, match="checksum"):
        store.events()
    assert len(calls) == 2
