"""restore copies everything the database holds, refuses what is not one, and hands out a new key."""

import sqlite3

from typer.testing import CliRunner

from logsentinel.cli import app
from logsentinel.portal.store import Store


def restore(backup, target):
    return CliRunner().invoke(app, ["restore", str(backup), "--data-dir", str(target)])


def test_rows_still_in_the_write_ahead_log_are_restored(tmp_path):
    source = Store(tmp_path / "live")
    held = sqlite3.connect(source.directory / "sentinel.db")
    held.execute("PRAGMA journal_mode=WAL")
    held.execute("INSERT INTO meta VALUES('marker','WAL-ONLY-XYZ')")
    held.commit()
    # A reader with an open transaction keeps the WAL from being checkpointed,
    # as the running portal's own readers do.
    reader = sqlite3.connect(source.directory / "sentinel.db")
    reader.execute("BEGIN")
    reader.execute("SELECT 1 FROM meta").fetchone()
    assert (source.directory / "sentinel.db-wal").stat().st_size > 0
    result = restore(source.directory / "sentinel.db", tmp_path / "restored")
    assert result.exit_code == 0, result.output
    assert Store(tmp_path / "restored").meta("marker") == "WAL-ONLY-XYZ"
    reader.close()
    held.close()


def test_a_file_that_is_not_a_database_is_refused_with_a_plain_message(tmp_path):
    bogus = tmp_path / "notes.db"
    bogus.write_text("this is not sqlite")
    result = restore(bogus, tmp_path / "restored")
    assert result.exit_code != 0
    assert "not a logsentinel database" in result.output.lower(), result.output
    assert "Traceback" not in result.output
    assert not (tmp_path / "restored").exists()


def test_a_missing_file_is_refused_the_same_way(tmp_path):
    result = restore(tmp_path / "missing.db", tmp_path / "restored")
    assert result.exit_code != 0 and "Traceback" not in result.output


def test_the_restored_copy_gets_a_new_access_key(tmp_path):
    source = Store(tmp_path / "original")
    old = source.meta("admin_token")
    backup = source.backup(tmp_path / "backup.db")
    result = restore(backup, tmp_path / "restored")
    assert result.exit_code == 0, result.output
    restored = Store(tmp_path / "restored")
    new = restored.meta("admin_token")
    assert new != old
    assert (tmp_path / "restored" / "access-key.txt").read_text().strip() == new
    assert old in restored.meta("retired_admin_tokens"), "the old key is kept for redaction only"
