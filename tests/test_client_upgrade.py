"""Use real SQLite backups/migrations while substituting systemd and account tools."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from logsentinel import client_setup as setup
from logsentinel.portal.models import Source
from logsentinel.portal.store import Store


def arranged(tmp_path, monkeypatch, active):
    install = tmp_path / "install"
    install.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    data = tmp_path / "data"
    data.mkdir()
    units = tmp_path / "units"
    units.mkdir()
    for key, value in [
        ("INSTALL", install),
        ("CONFIG", config),
        ("DATA", data),
        ("UNITS", units),
    ]:
        monkeypatch.setattr(setup, key, value)
    desired = setup.selection(
        "logs", dict(receiver="https://127.0.0.1:8767", source_id="synthetic-source")
    )
    cfg = config / "logs.json"
    cfg.write_text(json.dumps(desired))
    cfg.chmod(0o640)
    spool = Path(desired["spool"])
    store = Store(spool)
    source = dict(
        Source(
            name="legacy", machine_id="sender", kind="journald", enabled=True
        ).model_dump(),
        id="sender",
    )
    store.put("source", {k: v for k, v in source.items() if k != "id"}, "sender")
    store.set_meta(
        "sender_binding",
        json.dumps(
            ["journal", desired["receiver"], desired["source_id"]],
            separators=(",", ":"),
        ),
    )
    store.ingest(
        source,
        [dict(origin="a", message="first"), dict(origin="b", message="second")],
        "journal",
        {"cursor": "last"},
    )
    (spool / "push-token").write_text("synthetic-private-token")
    (spool / "receiver-ca.pem").write_text("synthetic-ca")
    unit = units / "logsentinel-client-logs.service"
    unit.write_text("old service")
    unit.chmod(0o644)
    real_stat = Path.stat

    def stat(path, *args, **kwargs):
        result = real_stat(path, *args, **kwargs)
        if path in (cfg, unit):
            values = list(result)
            values[4] = 0
            return os.stat_result(values)
        return result

    monkeypatch.setattr(Path, "stat", stat)
    monkeypatch.setattr(setup.os, "chown", lambda *_: None)
    monkeypatch.setattr(setup.os, "fchown", lambda *_: None)
    monkeypatch.setattr(
        setup.pwd,
        "getpwnam",
        lambda _: SimpleNamespace(
            pw_uid=os.getuid() or 1000, pw_gid=os.getgid(), pw_shell="/usr/sbin/nologin"
        ),
    )
    # The test may run as root; emulate the existing spool's service ownership.
    if os.getuid() == 0:

        def owned_stat(path, *args, **kwargs):
            result = stat(path, *args, **kwargs)
            if path == spool:
                values = list(result)
                values[4] = 1000
                return os.stat_result(values)
            return result

        monkeypatch.setattr(Path, "stat", owned_stat)
    monkeypatch.setattr("logsentinel.portal.sender_safety.io_pressure", lambda: 0)
    calls = []

    def run(argv, **kwargs):
        calls.append([str(a) for a in argv])
        return SimpleNamespace(returncode=0 if active else 3)

    monkeypatch.setattr(setup.subprocess, "run", run)

    def command(*argv, **kwargs):
        argv = [str(a) for a in argv]
        calls.append(argv)
        if argv[0] == "runuser":
            position = argv.index("logsentinel.client_setup")
            setup.main(argv[position + 1 :])

    monkeypatch.setattr(setup, "command", command)
    expected = [(e["id"], e["origin"]) for e in store.events()]
    original_config = cfg.read_bytes()
    runtime = install / "runtime-upgraded"
    runtime.mkdir()
    args = SimpleNamespace(name="logs")
    return SimpleNamespace(
        store=store, cfg=cfg, spool=spool, unit=unit, desired=desired, runtime=runtime,
        args=args, calls=calls, install=install, expected=expected,
        original_config=original_config,
    )


@pytest.mark.parametrize("active", [False, True])
def test_upgrade_legacy_queue_preserves_identity_evidence_and_service_state(
    tmp_path, monkeypatch, active
):
    ctx = arranged(tmp_path, monkeypatch, active)
    store, cfg, spool, unit, desired = ctx.store, ctx.cfg, ctx.spool, ctx.unit, ctx.desired
    runtime, args, calls, install = ctx.runtime, ctx.args, ctx.calls, ctx.install
    expected, original_config = ctx.expected, ctx.original_config
    setup.upgrade_client(args, desired, runtime)
    assert [(e["id"], e["origin"]) for e in store.events()] == expected
    assert cfg.read_bytes() == original_config
    assert store.cursor("sender", "journal") == {"cursor": "last"}
    assert (spool / "push-token").read_text() == "synthetic-private-token"
    assert (spool / "receiver-ca.pem").read_text() == "synthetic-ca"
    assert store.sender_pending() == 2
    backups = list(install.glob("backup-*"))
    assert len(backups) == 1
    backup = Store(backups[0])
    assert [(e["id"], e["origin"]) for e in backup.events()] == expected
    assert any(c[:2] == ["systemctl", "start"] for c in calls) == active
    assert not any("enroll" in c or "enable" in c for c in calls)
    assert "RestartSec=60" in unit.read_text() and "IOWeight=10" in unit.read_text()
    setup.upgrade_client(args, desired, runtime)
    assert len(list(install.glob("backup-*"))) == 2
    assert [(e["id"], e["origin"]) for e in store.events()] == expected


def test_backup_is_made_inside_the_spool_and_adopted_by_root(tmp_path, monkeypatch):
    import stat

    ctx = arranged(tmp_path, monkeypatch, True)
    setup.upgrade_client(ctx.args, ctx.desired, ctx.runtime)
    call = next(c for c in ctx.calls if "backup" in c and "--target" in c)
    staged = Path(call[call.index("--target") + 1])
    # Only the sender account's own spool is writable by it, so the copy is
    # made there; root then adopts it and the intermediate file is gone.
    assert staged.parent == ctx.spool
    assert not staged.exists() and not list(ctx.spool.glob("upgrade-backup-*"))
    (backup,) = ctx.install.glob("backup-*")
    assert stat.S_IMODE(backup.stat().st_mode) == 0o700
    assert stat.S_IMODE((backup / "sentinel.db").stat().st_mode) == 0o600
    assert [(e["id"], e["origin"]) for e in Store(backup).events()] == ctx.expected


def test_service_running_before_a_failed_upgrade_is_resumed_on_the_retry(tmp_path, monkeypatch):
    ctx = arranged(tmp_path, monkeypatch, True)
    monkeypatch.setattr("logsentinel.portal.sender_safety.io_pressure", lambda: 90)
    with pytest.raises(ValueError, match="presión"):
        setup.upgrade_client(ctx.args, ctx.desired, ctx.runtime)
    marker = ctx.install / "resume-logs"
    assert marker.exists()

    def stopped(argv, **kwargs):
        ctx.calls.append([str(a) for a in argv])
        return SimpleNamespace(returncode=3)

    monkeypatch.setattr(setup.subprocess, "run", stopped)
    monkeypatch.setattr("logsentinel.portal.sender_safety.io_pressure", lambda: 0)
    ctx.calls.clear()
    setup.upgrade_client(ctx.args, ctx.desired, ctx.runtime)
    assert any(c[:2] == ["systemctl", "start"] for c in ctx.calls)
    assert not marker.exists()


def test_service_stopped_on_purpose_stays_stopped_and_leaves_no_marker(tmp_path, monkeypatch):
    ctx = arranged(tmp_path, monkeypatch, False)
    setup.upgrade_client(ctx.args, ctx.desired, ctx.runtime)
    assert not any(c[:2] == ["systemctl", "start"] for c in ctx.calls)
    assert not (ctx.install / "resume-logs").exists()


def test_root_adopts_only_regular_files_and_never_follows_links(tmp_path):
    import stat

    real = tmp_path / "real.db"
    real.write_bytes(b"sqlite bytes")
    link = tmp_path / "link.db"
    link.symlink_to(real)
    with pytest.raises(OSError):
        setup.adopt_backup(link, tmp_path / "from-link")
    (tmp_path / "folder").mkdir()
    with pytest.raises((ValueError, OSError)):
        setup.adopt_backup(tmp_path / "folder", tmp_path / "from-folder")
    assert real.exists()
    setup.adopt_backup(real, tmp_path / "adopted")
    assert (tmp_path / "adopted").read_bytes() == b"sqlite bytes"
    assert stat.S_IMODE((tmp_path / "adopted").stat().st_mode) == 0o600
    assert not real.exists()


def test_sender_backup_needs_a_new_file(tmp_path, monkeypatch):
    ctx = arranged(tmp_path, monkeypatch, False)
    existing = ctx.spool / "already-there.db"
    existing.write_bytes(b"planted")
    with pytest.raises(FileExistsError):
        setup.backup_sender(ctx.cfg, existing)
    assert existing.read_bytes() == b"planted"


def test_sender_unit_is_confined_and_systemd_accepts_it(tmp_path):
    import shutil
    import subprocess

    desired = setup.selection("logs", dict(receiver="https://127.0.0.1:8767", source_id="s"))
    text = setup.unit_text(Path("/etc/logsentinel-clients/logs.json"), Path("/opt/logsentinel-client/runtime-x"), desired)
    for directive in (
        "NoNewPrivileges=yes", "CapabilityBoundingSet=", "ProtectSystem=strict", "PrivateDevices=yes",
        "ProtectKernelTunables=yes", "ProtectKernelModules=yes", "ProtectControlGroups=yes",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK", "RestrictNamespaces=yes",
        "RestrictSUIDSGID=yes", "LockPersonality=yes",
    ):
        assert directive in text
    if not shutil.which("systemd-analyze"):
        pytest.skip("systemd-analyze is not installed")
    runnable = (
        text.replace("User=" + desired["account"], "User=root")
        .replace("Group=" + desired["account"], "Group=root")
        .replace("ReadWritePaths=" + desired["spool"], "ReadWritePaths=" + str(tmp_path))
    )
    runnable = "\n".join(
        "ExecStart=/bin/true" if line.startswith("ExecStart=") else line for line in runnable.splitlines()
    )
    unit = tmp_path / "logsentinel-client-test.service"
    unit.write_text(runnable)
    result = subprocess.run(["systemd-analyze", "verify", str(unit)], capture_output=True, text=True)
    assert "Unknown key" not in result.stderr and "Unknown section" not in result.stderr, result.stderr


def test_sender_unit_bounds_cpu_and_memory():
    from pathlib import Path

    text = setup.unit_text(Path("/etc/logsentinel-clients/logs.json"), Path("/opt/logsentinel/runtime-x"), dict(name="logs", account="ls-logs", spool="/var/lib/logsentinel/logs"))
    for directive in ("CPUQuota=25%", "MemoryHigh=192M", "MemoryMax=256M", "OOMScoreAdjust=500", "Nice=10"):
        assert directive in text, directive
