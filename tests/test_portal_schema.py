import sqlite3

import pytest

from logsentinel.portal.store import MIGRATIONS, SCHEMA_VERSION, Store, schema_version


def indexes(path):
    with sqlite3.connect(path) as db:
        return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='index'")}


def test_new_database_is_at_the_current_version_with_every_migration_index(tmp_path):
    store = Store(tmp_path)
    with store.connect() as db:
        assert schema_version(db) == SCHEMA_VERSION
    names = indexes(store.path)
    for statements in MIGRATIONS.values():
        for statement in statements:
            if statement.startswith("CREATE INDEX"):
                assert statement.split()[5] in names
    with store.connect() as db:
        assert "urgent" in {r[1] for r in db.execute("PRAGMA table_info(events)")}


def test_version_one_database_is_upgraded_in_place_without_losing_data(tmp_path):
    store = Store(tmp_path)
    store.set_meta("keep", "me")
    with store.connect() as db:
        for name in ("signal_hits_event", "events_segment", "usage_created", "usage_job", "events_urgent", "events_pick", "templates_age", "events_shape"):
            db.execute(f"DROP INDEX {name}")
        db.execute("ALTER TABLE events DROP COLUMN urgent")
        db.execute("ALTER TABLE events DROP COLUMN rank")
        db.execute("ALTER TABLE events DROP COLUMN shape")
        db.execute("DROP TABLE templates")
        db.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
    reopened = Store(tmp_path)
    with reopened.connect() as db:
        assert schema_version(db) == SCHEMA_VERSION
    assert {"signal_hits_event", "events_segment", "usage_created", "usage_job", "events_urgent", "events_pick", "templates_age", "events_shape"} <= indexes(reopened.path)
    assert reopened.meta("keep") == "me"


def test_database_from_a_newer_version_is_refused(tmp_path):
    store = Store(tmp_path)
    with store.connect() as db:
        db.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION + 1),))
    with pytest.raises(RuntimeError, match="Unsupported schema version"):
        Store(tmp_path)


def test_deleting_events_uses_the_index_on_signal_hits(tmp_path):
    store = Store(tmp_path)
    with store.connect() as db:
        plan = " ".join(
            r[3] for r in db.execute("EXPLAIN QUERY PLAN DELETE FROM signal_hits WHERE event_id=?", ("x",))
        )
    assert "signal_hits_event" in plan


def test_unchanged_meta_value_does_not_commit(tmp_path):
    store = Store(tmp_path)
    store.set_meta("worker_error", "")
    watcher = sqlite3.connect(store.path)
    try:
        before = watcher.execute("PRAGMA data_version").fetchone()[0]
        store.set_meta("worker_error", "")
        assert watcher.execute("PRAGMA data_version").fetchone()[0] == before
        store.set_meta("worker_error", "failed")
        assert watcher.execute("PRAGMA data_version").fetchone()[0] != before
    finally:
        watcher.close()


def test_restore_accepts_older_backups_and_rejects_newer_ones(tmp_path):
    from typer.testing import CliRunner

    from logsentinel.cli import app

    store = Store(tmp_path / "live")
    good = store.backup(tmp_path / "good.db")
    with store.connect() as db:
        db.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(SCHEMA_VERSION + 1),))
    future = store.backup(tmp_path / "future.db")
    runner = CliRunner()
    ok = runner.invoke(app, ["restore", str(good), "--data-dir", str(tmp_path / "restored")])
    assert ok.exit_code == 0, ok.output
    bad = runner.invoke(app, ["restore", str(future), "--data-dir", str(tmp_path / "rejected")])
    assert bad.exit_code != 0
    assert not (tmp_path / "rejected").exists()


def test_processes_starting_together_migrate_once_without_failing(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    store = Store(tmp_path)
    with store.connect() as db:
        for name in ("signal_hits_event", "events_segment", "usage_created", "usage_job", "events_urgent", "events_pick", "templates_age", "events_shape"):
            db.execute(f"DROP INDEX {name}")
        db.execute("ALTER TABLE events DROP COLUMN urgent")
        db.execute("ALTER TABLE events DROP COLUMN rank")
        db.execute("ALTER TABLE events DROP COLUMN shape")
        db.execute("DROP TABLE templates")
        db.execute("UPDATE meta SET value='1' WHERE key='schema_version'")

    def start(_):
        with Store(tmp_path).connect() as db:
            return schema_version(db)

    with ThreadPoolExecutor(max_workers=6) as pool:
        versions = list(pool.map(start, range(6)))
    assert versions == [SCHEMA_VERSION] * 6
