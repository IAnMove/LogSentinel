"""A system unit says when its account cannot reach the interpreter, and takes the portal's listen options."""

import getpass
import grp
import os
import pwd
import sys
from types import SimpleNamespace

from typer.testing import CliRunner

from logsentinel import cli


def install(tmp_path, monkeypatch, *args, venv_mode=0o600):
    """The account is the test's own user, so the data directory it creates is its own.

    A home without search permission for anyone, mode 0600, stands in for a
    0700 home of another user: the account cannot pass through it either way.
    """
    home = tmp_path / "agent-home"
    venv = tmp_path / "installer-home" / ".venv" / "bin"
    venv.mkdir(parents=True)
    (venv / "python").write_text("")
    (tmp_path / "installer-home").chmod(venv_mode)
    monkeypatch.setattr(sys, "executable", str(venv / "python"))
    account = SimpleNamespace(pw_name="logsentinel-agent", pw_dir=str(home), pw_uid=os.geteuid(), pw_gid=os.getegid())
    monkeypatch.setattr(pwd, "getpwnam", lambda name: account)
    monkeypatch.setattr(grp, "getgrgid", lambda gid: SimpleNamespace(gr_name="log-readers"))
    monkeypatch.setattr(getpass, "getuser", lambda: "root")
    monkeypatch.setattr(cli.Path, "home", classmethod(lambda cls: tmp_path / "installer-home"))
    monkeypatch.setattr(cli, "SYSTEM_UNIT_DIR", tmp_path / "units")
    try:
        result = CliRunner().invoke(cli.app, ["service", "install", "--system", "--run-as", "logsentinel-agent", *args])
    finally:
        (tmp_path / "installer-home").chmod(0o755)
    assert result.exit_code == 0, result.output
    return result, (tmp_path / "units" / "logsentinel.service").read_text()


def test_a_venv_inside_a_private_home_is_reported_as_unreachable(tmp_path, monkeypatch):
    result, unit = install(tmp_path, monkeypatch)
    assert "cannot search" in result.output and "installer-home" in result.output


def test_a_world_searchable_install_location_raises_no_warning(tmp_path, monkeypatch):
    result, unit = install(tmp_path, monkeypatch, venv_mode=0o755)
    assert "cannot search" not in result.output


def test_the_unit_takes_the_port_and_the_reception_listener(tmp_path, monkeypatch):
    cert = tmp_path / "c.pem"
    key = tmp_path / "k.pem"
    cert.write_text("")
    key.write_text("")
    result, unit = install(tmp_path, monkeypatch, "--port", "9000", "--ingest-listen", "0.0.0.0:8767", "--tls-cert", str(cert), "--tls-key", str(key), venv_mode=0o755)
    assert "--port 9000" in unit and "--ingest-listen 0.0.0.0:8767" in unit
    assert f"--tls-cert {cert}" in unit and f"--tls-key {key}" in unit


def test_a_listener_with_only_one_half_of_the_tls_pair_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "SYSTEM_UNIT_DIR", tmp_path / "units")
    result = CliRunner().invoke(cli.app, ["service", "install", "--ingest-listen", "0.0.0.0:8767", "--tls-cert", "/x.pem"])
    assert result.exit_code != 0 and "both" in result.output.lower()
    assert not (tmp_path / "units").exists()
