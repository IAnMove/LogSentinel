import os
import shutil
import stat
import time

import pytest

from logsentinel.portal import store as store_module
from logsentinel.portal.store import BACKUPS_KEPT, LEDGER_MIN_DAYS, Store

DAY = 86400


def seed(store):
    """One old and one recent row in every table that used to grow forever."""
    now = time.time()
    old, recent = now - 60 * DAY, now - DAY
    ancient = now - (LEDGER_MIN_DAYS + 30) * DAY
    with store.connect() as db:
        for name, updated, status in (
            ("old-done", old, "done"), ("old-failed", old, "failed"),
            ("new-done", recent, "done"), ("old-running", old, "running"),
            ("old-pending", old, "pending"),
        ):
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,0,'{}',NULL)",
                (name, "m", "[]", status, updated, updated),
            )
            db.execute("INSERT INTO review_batches VALUES(?,?)", (name, "{}"))
        for name, updated, status in (
            ("d-old-ok", old, "delivered"), ("d-old-pending", old, "pending"),
            ("d-old-retry", old, "retry"), ("d-new-ok", recent, "delivered"),
        ):
            db.execute(
                "INSERT INTO deliveries VALUES(?,?,?,?,?,0,?,?,?,NULL)",
                (name, "dest", "p", "{}", status, updated, updated, updated),
            )
        for name, created in (("u-ancient", ancient), ("u-old", old), ("u-new", recent)):
            db.execute(
                "INSERT INTO usage VALUES(?,?,?,?,?,?,1,1,1,'ok','')",
                (name, "j", "m", "[]", "analysis", created),
            )
        for created in (ancient, recent):
            db.execute("INSERT INTO audit(created,action,object_id,detail) VALUES(?,?,?,?)", (created, "x", "", ""))


def names(store, table, column="id"):
    with store.connect() as db:
        return {r[0] for r in db.execute(f"SELECT {column} FROM {table}")}


def test_prune_bounds_tables_that_never_expired_but_keeps_live_work(tmp_path):
    store = Store(tmp_path)
    seed(store)
    store.prune()
    assert names(store, "jobs") == {"new-done", "old-running", "old-pending"}
    assert "old-done" not in names(store, "review_batches", "job_id")
    assert names(store, "deliveries") == {"d-old-pending", "d-old-retry", "d-new-ok"}
    # Token statistics outlive the evidence: only rows past a year go.
    assert names(store, "usage") == {"u-old", "u-new"}
    assert len(names(store, "audit")) == 1


def fill_and_free(store):
    with store.connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS filler(x BLOB)")
        db.executemany("INSERT INTO filler VALUES(?)", [(os.urandom(1000),) for _ in range(4000)])
    with store.connect() as db:
        db.execute("DELETE FROM filler")


def test_vacuum_is_skipped_below_the_thresholds(tmp_path):
    store = Store(tmp_path)
    fill_and_free(store)
    before = store.size()
    assert store.compact_if_worthwhile() is False
    assert store.size() == before


def test_vacuum_shrinks_the_file_when_it_pays_and_the_disk_can_hold_a_copy(tmp_path, monkeypatch):
    store = Store(tmp_path)
    fill_and_free(store)
    monkeypatch.setattr(store_module, "VACUUM_MIN_RECLAIM", 1)
    before = store.size()
    assert store.compact_if_worthwhile() is True
    assert store.size() < before


def test_vacuum_never_runs_when_the_disk_cannot_hold_a_second_copy(tmp_path, monkeypatch):
    store = Store(tmp_path)
    fill_and_free(store)
    monkeypatch.setattr(store_module, "VACUUM_MIN_RECLAIM", 1)
    monkeypatch.setattr(
        shutil, "disk_usage", lambda path: shutil._ntuple_diskusage(10**12, 10**12 - 1024, 1024)
    )
    assert store.compact_if_worthwhile() is False


def test_backup_is_private_and_atomic(tmp_path):
    store = Store(tmp_path / "live")
    target = tmp_path / "backups" / "backup-1.db"
    target.parent.mkdir()
    store.backup(target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert not list(target.parent.glob("*.partial"))
    assert Store(tmp_path / "check") is not None
    with pytest.raises(ValueError, match="already exists"):
        store.backup(target)


def test_backup_refuses_when_the_disk_is_too_full_and_leaves_nothing(tmp_path, monkeypatch):
    store = Store(tmp_path / "live")
    monkeypatch.setattr(
        shutil, "disk_usage", lambda path: shutil._ntuple_diskusage(10**9, 10**9 - 1024, 1024)
    )
    target = tmp_path / "backup.db"
    with pytest.raises(ValueError, match="free disk space"):
        store.backup(target)
    assert not list(tmp_path.glob("backup*"))


def test_failed_backup_removes_the_partial_file(tmp_path, monkeypatch):
    store = Store(tmp_path / "live")

    def broken(source, target):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken)
    target = tmp_path / "backup.db"
    with pytest.raises(OSError):
        store.backup(target)
    assert not list(tmp_path.glob("backup*"))


def test_only_the_newest_backups_are_kept(tmp_path):
    for i in range(BACKUPS_KEPT + 3):
        path = tmp_path / f"backup-{i}.db"
        path.write_text("x")
        os.utime(path, (1000 + i, 1000 + i))
    (tmp_path / "notes.txt").write_text("unrelated")
    assert Store.rotate_backups(tmp_path) == 3
    kept = sorted(p.name for p in tmp_path.glob("backup-*.db"))
    assert kept == [f"backup-{i}.db" for i in range(3, BACKUPS_KEPT + 3)]
    assert (tmp_path / "notes.txt").exists()
