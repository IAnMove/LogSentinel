"""Use real SQLite backups/migrations while substituting systemd and account tools."""

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from logsentinel import client_setup as setup
from logsentinel.portal.models import Source
from logsentinel.portal.store import Store


@pytest.mark.parametrize("active", [False, True])
def test_upgrade_legacy_queue_preserves_identity_evidence_and_service_state(
    tmp_path, monkeypatch, active
):
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
