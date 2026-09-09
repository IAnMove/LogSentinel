"""Host preparation plans the change, refuses the dangerous ones, and proves the result."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from logsentinel import cli, hostprep


@pytest.fixture
def logs(tmp_path):
    folder = tmp_path / "logs"
    folder.mkdir()
    (folder / "app.log").write_text("synthetic line\n")
    return folder


@pytest.mark.parametrize("target", ["/", "/etc", "/home", "/var", "/root"])
def test_whole_system_directories_are_refused(target):
    with pytest.raises(ValueError, match="Refusing"):
        hostprep.check_source(target)


def test_a_relative_or_missing_path_is_refused(tmp_path):
    with pytest.raises(ValueError, match="absolute"):
        hostprep.check_source("var/log/app.log")
    with pytest.raises(ValueError, match="No such path"):
        hostprep.check_source(str(tmp_path / "absent.log"))


def test_a_file_grant_stays_a_file_grant(logs, monkeypatch):
    monkeypatch.setattr(hostprep, "group_exists", lambda name: False)
    monkeypatch.setattr(hostprep, "account_exists", lambda name: False)
    source = hostprep.check_source(str(logs / "app.log"))
    commands = [" ".join(step["command"]) for step in hostprep.plan("agent", [source])]
    assert commands[0] == "groupadd --system logsentinel-read"
    assert "useradd --system --no-create-home --shell /usr/sbin/nologin --gid logsentinel-read agent" in commands
    assert f"setfacl -m u:agent:r {source}" in commands
    # A default ACL on the parent would grant every other file landing there,
    # which is wider than what was asked for; it is raised as a note instead.
    assert not any(f"-d -m u:agent:r {source.parent}" in c for c in commands)
    note = hostprep.rotation_notes([source], "agent")[0]
    assert "Rotation replaces it" in note and "logrotate" in note
    # Nothing here changes the file's owner or group.
    assert not any(c.startswith("chown") or c.startswith("chgrp") for c in commands)


def test_an_existing_account_is_joined_rather_than_recreated(logs, monkeypatch):
    monkeypatch.setattr(hostprep, "group_exists", lambda name: True)
    monkeypatch.setattr(hostprep, "account_exists", lambda name: True)
    source = hostprep.check_source(str(logs / "app.log"))
    commands = [" ".join(step["command"]) for step in hostprep.plan("agent", [source])]
    assert not any(c.startswith("useradd") for c in commands)
    assert not any(c.startswith("groupadd") for c in commands)
    assert "usermod --append --groups logsentinel-read agent" in commands


def test_the_journal_grant_says_what_it_hands_over(logs, monkeypatch):
    monkeypatch.setattr(hostprep, "group_exists", lambda name: True)
    monkeypatch.setattr(hostprep, "account_exists", lambda name: True)
    steps = hostprep.plan("agent", [], journal=True)
    journal = [s for s in steps if hostprep.JOURNAL_GROUP in s["command"]]
    assert len(journal) == 1
    assert "every service" in journal[0]["why"]


def test_applying_without_root_changes_nothing(logs, monkeypatch):
    monkeypatch.setattr(hostprep.os, "geteuid", lambda: 1000)
    ran = []
    with pytest.raises(PermissionError):
        hostprep.apply([{"command": ["true"], "why": ""}], runner=lambda *a, **k: ran.append(a))
    assert ran == []


def test_a_failed_step_stops_the_rest(monkeypatch):
    monkeypatch.setattr(hostprep.os, "geteuid", lambda: 0)
    attempted = []

    def runner(command, **kwargs):
        attempted.append(command)
        code = 1 if command[0] == "setfacl" else 0
        return SimpleNamespace(returncode=code, stderr="synthetic refusal", stdout="")

    steps = [
        {"command": ["groupadd", "x"], "why": ""},
        {"command": ["setfacl", "y"], "why": ""},
        {"command": ["usermod", "z"], "why": ""},
    ]
    with pytest.raises(RuntimeError, match="synthetic refusal"):
        hostprep.apply(steps, runner=runner)
    assert attempted == [["groupadd", "x"], ["setfacl", "y"]]


def test_verification_reads_as_the_account_not_as_root(logs):
    calls = []

    def runner(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    source = hostprep.check_source(str(logs / "app.log"))
    results = hostprep.verify("agent", [source], journal=True, runner=runner)
    assert all(command[:3] == ["runuser", "-u", "agent"] for command in calls)
    assert [r["readable"] for r in results] == [True, True]
    assert results[-1]["target"] == "journal"


def test_the_command_shows_the_plan_and_touches_nothing_without_apply(logs, monkeypatch):
    applied = []
    monkeypatch.setattr(hostprep, "apply", lambda *a, **k: applied.append(a))
    result = CliRunner().invoke(
        cli.app, ["prepare-host", "--account", "agent", "--source", str(logs / "app.log")]
    )
    assert result.exit_code == 0, result.exception
    assert "setfacl" in result.output
    assert "Nothing was changed" in result.output
    assert applied == []


def test_the_command_needs_something_to_grant(tmp_path):
    result = CliRunner().invoke(cli.app, ["prepare-host", "--account", "agent"])
    assert result.exit_code != 0
    assert "--source" in result.output
