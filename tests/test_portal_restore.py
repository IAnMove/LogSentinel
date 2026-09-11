from typer.testing import CliRunner
from logsentinel.cli import app
from logsentinel.portal.store import Store


def test_restore_validates_and_never_overwrites(tmp_path):
    source = Store(tmp_path / "original")
    source.set_meta("custom-marker", "retained")
    backup = source.backup(tmp_path / "backup with ? question.db")
    target = tmp_path / "restored"
    runner = CliRunner()
    result = runner.invoke(app, ["restore", str(backup), "--data-dir", str(target)])
    assert result.exit_code == 0, result.output
    restored = Store(target)
    assert restored.meta("custom-marker") == "retained"
    key = restored.meta("admin_token")
    assert (target / "access-key.txt").read_text().strip() == key
    assert "rotate" in result.output.lower()
    result = runner.invoke(app, ["restore", str(backup), "--data-dir", str(target)])
    assert result.exit_code != 0
    assert Store(target).meta("custom-marker") == "retained"
