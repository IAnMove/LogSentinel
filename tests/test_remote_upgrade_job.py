"""Root on a sender host installs an offered commit only after verifying it itself."""

import fcntl
import json
import os
import subprocess
import time
from types import SimpleNamespace

import pytest

from logsentinel import client_setup as setup

# A clean environment: under `git rebase --exec` the parent exports GIT_DIR,
# which would point every command here at the repository being rebased.
GIT = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
GIT.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@x", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@x")


def sh(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True, env=GIT).stdout.strip()


def release(checkout, version, message):
    (checkout / "logsentinel").mkdir(exist_ok=True)
    (checkout / "logsentinel" / "__init__.py").write_text('__version__ = "%s"\n' % version)
    sh("add", "-A", cwd=checkout)
    sh("commit", "-q", "-m", message, cwd=checkout)
    return sh("rev-parse", "HEAD", cwd=checkout)


@pytest.fixture
def host(tmp_path, monkeypatch):
    """A bare origin, the operator's checkout, and an installed sender "logs" on this host."""
    origin = tmp_path / "origin.git"
    sh("init", "-q", "--bare", str(origin))
    operator = tmp_path / "operator"
    sh("init", "-q", str(operator))
    sh("symbolic-ref", "HEAD", "refs/heads/main", cwd=operator)
    sh("remote", "add", "origin", str(origin), cwd=operator)
    first = release(operator, "1.1.0", "first")
    sh("push", "-q", "origin", "main", cwd=operator)
    install, config, units, spool = tmp_path / "opt", tmp_path / "etc", tmp_path / "units", tmp_path / "spool"
    for d in (install, config, units, spool):
        d.mkdir()
    monkeypatch.setattr(setup, "INSTALL", install)
    monkeypatch.setattr(setup, "SOURCE", install / "source")
    monkeypatch.setattr(setup, "CONFIG", config)
    monkeypatch.setattr(setup, "UNITS", units)
    monkeypatch.setattr(setup, "managed_directory", lambda path, mode=0o755: setup.Path(path).mkdir(parents=True, exist_ok=True))
    cfg = dict(name="logs", account="ls-logs", spool=str(spool), journal=True, path=None)
    (config / "logs.json").write_text(json.dumps(cfg))
    monkeypatch.setattr(setup, "read_config", lambda name: (config / (name + ".json"), json.loads((config / (name + ".json")).read_text())))
    monkeypatch.setattr(setup.pwd, "getpwnam", lambda account: SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid()))
    monkeypatch.setattr(setup, "disk_pressure", lambda: 0)
    commands = []
    monkeypatch.setattr(setup, "command", lambda *a, **k: commands.append(tuple(str(x) for x in a)))
    monkeypatch.setattr(setup, "quiet", lambda *a: commands.append(tuple(str(x) for x in a)))
    installs = []

    def installer(name):
        installs.append(name)
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(setup, "run_installer", installer)
    return SimpleNamespace(origin=origin, operator=operator, first=first, install=install, config=config / "logs.json",
                           units=units, spool=spool, commands=commands, installs=installs)


def request(host, commit, version="1.2.0", raw=None):
    (host.spool / setup.REQUEST_FILE).write_text(raw if raw is not None else json.dumps(dict(commit=commit, version=version)))


def state(host):
    return json.loads((host.install / "upgrade-logs.json").read_text())


def test_enabling_clones_the_operators_repository_and_records_the_installed_commit(host, monkeypatch):
    calls = []
    real = setup.git
    monkeypatch.setattr(setup, "git", lambda *a, **k: (calls.append((a, k.get("cwd"))), real(*a, **k))[1])
    setup.enable_remote_upgrade("logs", host.operator)
    # Root reads a checkout owned by the operator: git must be told to trust
    # that one path, and the clone must not share inodes with it.
    trust = ("-c", "safe.directory=" + str(host.operator.resolve()))
    reads = [a for a, cwd in calls if cwd == host.operator or "clone" in a]
    assert len(reads) == 3 and all(a[:2] == trust for a in reads)
    assert "--no-hardlinks" in next(a for a in reads if "clone" in a)
    assert ("systemctl", "try-restart", "logsentinel-client-logs.service") in host.commands
    cfg = json.loads(host.config.read_text())
    assert cfg["remote_upgrade"] is True and cfg["source_remote"] == str(host.origin) and cfg["source_branch"] == "main"
    assert sh("remote", "get-url", "origin", cwd=host.install / "source") == str(host.origin)
    assert state(host)["status"] == "installed" and state(host)["commit"] == host.first and state(host)["version"] == "1.1.0"
    assert (host.units / "logsentinel-client-upgrade-logs.timer").exists()
    service = (host.units / "logsentinel-client-upgrade-logs.service").read_text()
    assert "remote-upgrade --name logs" in service and str(host.install / "source") in service
    assert ("systemctl", "enable", "--now", "logsentinel-client-upgrade-logs.timer") in host.commands


def test_a_published_descendant_is_checked_out_and_installed_once(host):
    setup.enable_remote_upgrade("logs", host.operator)
    second = release(host.operator, "1.2.0", "second")
    sh("push", "-q", "origin", "main", cwd=host.operator)
    request(host, second)
    assert setup.remote_upgrade("logs") == "installed"
    assert host.installs == ["logs"]
    assert sh("rev-parse", "HEAD", cwd=host.install / "source") == second
    assert state(host)["status"] == "installed" and state(host)["commit"] == second
    assert setup.remote_upgrade("logs") == "done" and host.installs == ["logs"]


def test_an_unpublished_commit_is_refused_even_though_it_exists(host):
    setup.enable_remote_upgrade("logs", host.operator)
    unpublished = release(host.operator, "1.2.0", "local only")
    request(host, unpublished)
    assert setup.remote_upgrade("logs") == "refused"
    assert host.installs == [] and "publicado" in state(host)["message"]
    sh("push", "-q", "origin", "main:feature", cwd=host.operator)
    assert setup.remote_upgrade("logs") == "refused"  # a branch other than the recorded one does not count
    assert sh("rev-parse", "HEAD", cwd=host.install / "source") == host.first


def test_going_back_to_an_older_build_is_refused(host):
    setup.enable_remote_upgrade("logs", host.operator)
    second = release(host.operator, "1.2.0", "second")
    sh("push", "-q", "origin", "main", cwd=host.operator)
    request(host, second)
    assert setup.remote_upgrade("logs") == "installed"
    request(host, host.first, version="1.1.0")
    assert setup.remote_upgrade("logs") == "refused" and "Retroceder" in state(host)["message"]
    # Same version number but an ancestor commit: the history check catches it.
    (host.install / "upgrade-logs.json").write_text(json.dumps(dict(status="installed", commit=second, version="")))
    assert setup.remote_upgrade("logs") == "refused" and "retroceso" in state(host)["message"]
    assert host.installs == ["logs"]


def test_a_version_that_is_not_the_commits_own_is_refused(host):
    setup.enable_remote_upgrade("logs", host.operator)
    second = release(host.operator, "1.2.0", "second")
    sh("push", "-q", "origin", "main", cwd=host.operator)
    request(host, second, version="9.9.9")
    assert setup.remote_upgrade("logs") == "refused" and "anunciada" in state(host)["message"]
    assert host.installs == []


@pytest.mark.parametrize("raw", [
    json.dumps(dict(commit="HEAD", version="1.2.0")),
    json.dumps(dict(commit="$(touch /tmp/pwned)", version="1.2.0")),
    json.dumps(dict(commit="a" * 40, version="1.2.0; rm -rf /")),
    "not json",
    json.dumps(dict(commit="a" * 40, version="1.2.0")) + " " * 5000,
])
def test_a_request_that_is_not_a_plain_commit_never_reaches_git(host, monkeypatch, raw):
    setup.enable_remote_upgrade("logs", host.operator)
    calls = []
    real = setup.git
    monkeypatch.setattr(setup, "git", lambda *a, **k: (calls.append(a), real(*a, **k))[1])
    request(host, None, raw=raw)
    assert setup.remote_upgrade("logs") == "refused"
    assert state(host)["message"].startswith("La petición del emisor")
    assert calls == [] and host.installs == []


def test_a_request_that_is_a_link_or_not_the_senders_is_ignored(host, monkeypatch):
    setup.enable_remote_upgrade("logs", host.operator)
    target = host.spool / "elsewhere.json"
    target.write_text(json.dumps(dict(commit="b" * 40, version="1.2.0")))
    (host.spool / setup.REQUEST_FILE).symlink_to(target)
    assert setup.remote_upgrade("logs") == "refused" and host.installs == []
    (host.spool / setup.REQUEST_FILE).unlink()
    request(host, "b" * 40)
    monkeypatch.setattr(setup.pwd, "getpwnam", lambda account: SimpleNamespace(pw_uid=os.getuid() + 1))
    assert setup.remote_upgrade("logs") == "refused" and host.installs == []


def test_without_the_hosts_permission_nothing_is_fetched_or_installed(host, monkeypatch):
    setup.enable_remote_upgrade("logs", host.operator)
    cfg = json.loads(host.config.read_text())
    cfg["remote_upgrade"] = False
    host.config.write_text(json.dumps(cfg))
    monkeypatch.setattr(setup, "git", lambda *a, **k: pytest.fail("no git while disabled"))
    request(host, "b" * 40)
    assert setup.remote_upgrade("logs") == "disabled" and state(host)["status"] == "disabled"


def test_an_installer_failure_after_the_backup_is_not_retried_but_a_preflight_one_is(host, monkeypatch):
    setup.enable_remote_upgrade("logs", host.operator)
    second = release(host.operator, "1.2.0", "second")
    sh("push", "-q", "origin", "main", cwd=host.operator)
    answers = [subprocess.CompletedProcess([], 1, "", "Falta espacio para copia y actualización. El cliente queda detenido y conserva su cola.\n")]
    monkeypatch.setattr(setup, "run_installer", lambda name: (host.installs.append(name), answers.pop(0))[1])
    request(host, second)
    assert setup.remote_upgrade("logs") == "deferred"
    first_state = state(host)
    assert first_state["attempts"] == 1 and first_state["next_after"] > time.time() + 600
    assert "Falta espacio" in first_state["message"]
    assert setup.remote_upgrade("logs") == "waiting" and len(host.installs) == 1
    answers.append(subprocess.CompletedProcess([], 1, "", "Actualización incompleta: cliente detenido; cola intacta. Directorio de respaldo: /opt/x\n"))
    monkeypatch.setattr(setup.time, "time", lambda: first_state["next_after"] + 1)
    assert setup.remote_upgrade("logs") == "failed" and len(host.installs) == 2
    assert state(host)["status"] == "failed"
    assert setup.remote_upgrade("logs") == "failed" and len(host.installs) == 2  # no third attempt
    third = release(host.operator, "1.3.0", "third")
    sh("push", "-q", "origin", "main", cwd=host.operator)
    answers.append(subprocess.CompletedProcess([], 0, "", ""))
    request(host, third, version="1.3.0")
    assert setup.remote_upgrade("logs") == "installed"  # a new target starts afresh


def test_the_job_and_a_manual_upgrade_share_one_lock(host, monkeypatch):
    setup.enable_remote_upgrade("logs", host.operator)
    request(host, "b" * 40)
    fd = os.open(host.install / "upgrade.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        assert setup.remote_upgrade("logs") == "busy" and host.installs == []
        with pytest.raises(ValueError, match="en curso"):
            setup.upgrade_lock()
        monkeypatch.setenv("LOGSENTINEL_UPGRADE_LOCK_HELD", "1")
        assert setup.upgrade_lock() is None  # the installer the job itself started
    finally:
        os.close(fd)


def test_denying_removes_the_timer_and_the_permission(host):
    setup.enable_remote_upgrade("logs", host.operator)
    setup.disable_remote_upgrade("logs")
    assert json.loads(host.config.read_text())["remote_upgrade"] is False
    assert not (host.units / "logsentinel-client-upgrade-logs.timer").exists()
    assert ("systemctl", "disable", "--now", "logsentinel-client-upgrade-logs.timer") in host.commands
    assert host.commands[-1] == ("systemctl", "try-restart", "logsentinel-client-logs.service")
    assert state(host)["status"] == "disabled"


def test_enabling_refuses_a_checkout_without_origin_or_a_different_remote(host, tmp_path):
    loose = tmp_path / "loose"
    sh("init", "-q", str(loose))
    release(loose, "1.1.0", "x")
    with pytest.raises(ValueError, match="origin"):
        setup.enable_remote_upgrade("logs", loose)
    setup.enable_remote_upgrade("logs", host.operator)
    sh("remote", "set-url", "origin", "https://example.invalid/other.git", cwd=host.operator)
    with pytest.raises(ValueError, match="otro remoto"):
        setup.enable_remote_upgrade("logs", host.operator)


def test_the_flags_exclude_each_other_and_the_job_needs_root(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        setup.main(["--upgrade", "--allow-remote-upgrade", "--deny-remote-upgrade"])
    monkeypatch.setattr(setup.os, "geteuid", lambda: 1000)
    with pytest.raises(ValueError, match="root"):
        setup.main(["remote-upgrade", "--name", "logs"])
