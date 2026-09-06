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


def test_gzip_stability_and_import_idempotency(setup):
    store, source, path = setup
    path = path.with_suffix(".log.gz")
    path.write_bytes(gzip.compress(b"one\ntwo\n"))
    c = Collector(store)
    assert c.file(source, path) == 0
    assert c.file(source, path) == 2
    assert c.file(source, path) == 0
    assert len(store.events()) == 2


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
