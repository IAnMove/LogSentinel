"""prepare-host takes an account name that is a name, and never a person's or root's account."""

import pwd
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from logsentinel import cli, hostprep


@pytest.mark.parametrize("name", ["--help", "a:b", "Agent", "", "with space", "x" * 33, "9abc"])
def test_names_that_are_not_account_names_are_refused(name, monkeypatch):
    monkeypatch.setattr(hostprep, "account_exists", lambda n: False)
    with pytest.raises(ValueError):
        hostprep.validate_account(name)


@pytest.mark.parametrize("name", ["logsentinel-agent", "ls_logs", "_svc", "a"])
def test_ordinary_names_pass(name, monkeypatch):
    monkeypatch.setattr(hostprep, "account_exists", lambda n: False)
    assert hostprep.validate_account(name) == name


def existing(uid, shell):
    return lambda n: SimpleNamespace(pw_name=n, pw_uid=uid, pw_shell=shell, pw_dir="/var/lib/x", pw_gid=1)


def test_root_and_login_accounts_are_refused_but_a_nologin_one_passes(monkeypatch):
    monkeypatch.setattr(hostprep, "account_exists", lambda n: True)
    monkeypatch.setattr(pwd, "getpwnam", existing(0, "/usr/sbin/nologin"))
    with pytest.raises(ValueError, match="root"):
        hostprep.validate_account("rootish")
    monkeypatch.setattr(pwd, "getpwnam", existing(1000, "/bin/bash"))
    with pytest.raises(ValueError, match="login account"):
        hostprep.validate_account("ina")
    monkeypatch.setattr(pwd, "getpwnam", existing(998, "/usr/sbin/nologin"))
    assert hostprep.validate_account("logsentinel-agent") == "logsentinel-agent"


def test_the_command_refuses_before_showing_any_plan(monkeypatch):
    monkeypatch.setattr(hostprep, "account_exists", lambda n: False)
    result = CliRunner().invoke(cli.app, ["prepare-host", "--account", "--help", "--journal"])
    assert result.exit_code != 0
    assert "account name" in result.output
    assert "useradd" not in result.output
