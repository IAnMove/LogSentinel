"""Set up the brain sender on a machine as a service of its own: one command.

Run as root on the machine that will report. It creates an account with no
login, a spool only that account can read, a unit confined like the log
sender's, and starts it. The token is kept in a root-only file systemd reads;
the account gets the journal group through the unit, not through its own
membership, so nothing else it might run inherits that.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from .brain_hook import install_hook, remove_hook

ACCOUNT = "ls-brain"
UNIT = "logsentinel-brain.service"
SPOOL = "var/lib/logsentinel-client/brain"
ENV_FILE = "etc/logsentinel-clients/brain.env"
UNIT_FILE = "etc/systemd/system/" + UNIT
CLIENT_HOME = "opt/logsentinel-client"
MACHINE = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,200}$")


def launcher(root="/", executable=None):
    """The command the unit starts.

    A client runtime lives in a directory that changes with every upgrade, so
    the unit picks the newest one each time it starts instead of naming one
    that an upgrade would leave behind."""
    executable = Path(executable or sys.executable)
    home = Path(root) / CLIENT_HOME
    if home in executable.parents:
        return (
            "/bin/sh -c 'exec \"$(ls -1dt " + str(home) + "/runtime-*/ | head -n 1)bin/logsentinel\" \"$@\"' logsentinel"
        )
    return str(executable.with_name("logsentinel"))


def unit_text(receiver, machine, activity, root="/", executable=None):
    spool = Path(root) / SPOOL
    command = (
        launcher(root, executable)
        + " brain-forward --receiver "
        + receiver
        + " --machine-id "
        + machine
        + " --spool "
        + str(spool)
        + ("" if activity else " --no-activity")
    )
    return f"""[Unit]
Description=LogSentinel brain sender (inventory and activity)
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User={ACCOUNT}
Group={ACCOUNT}
SupplementaryGroups=systemd-journal
EnvironmentFile={Path(root) / ENV_FILE}
ExecStart={command}
Restart=on-failure
RestartSec=60
Nice=10
IOSchedulingClass=idle
CPUQuota=25%
MemoryHigh=192M
MemoryMax=256M
UMask=0077
NoNewPrivileges=yes
CapabilityBoundingSet=
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6 AF_NETLINK
RestrictNamespaces=yes
RestrictSUIDSGID=yes
LockPersonality=yes
ReadWritePaths={spool}

[Install]
WantedBy=multi-user.target
"""


def system(arguments):
    done = subprocess.run(arguments, capture_output=True, text=True, timeout=120)
    if done.returncode:
        raise OSError(" ".join(arguments[:2]) + ": " + (done.stderr or done.stdout).strip()[-200:])
    return done.stdout


def write_private(path, text, mode):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
    os.chmod(path, mode)


def install(receiver, machine, token, ca_file=None, activity=True, hook=False, root="/", run=system, executable=None):
    """Install and start the brain sender. Returns what was done, line by line."""
    if not receiver.startswith("https://") or any(c.isspace() or c in "'\"\\$`;&|" for c in receiver):
        raise ValueError("The receiver must be an https:// address without spaces or shell characters")
    if not MACHINE.match(machine):
        raise ValueError("The machine id is the one shown by the central")
    if not TOKEN.match(token):
        raise ValueError("The token is the one generated in the Brain view")
    base = Path(root)
    done = []
    exists = True
    try:
        run(["id", ACCOUNT])
    except OSError:
        exists = False
    if not exists:
        run(["useradd", "--system", "--no-create-home", "--shell", "/usr/sbin/nologin", ACCOUNT])
        done.append("Created the account " + ACCOUNT + " (no login)")
    spool = base / SPOOL
    spool.mkdir(parents=True, exist_ok=True)
    os.chmod(spool, 0o700)
    # The authority the log sender on this machine already trusts, unless one is given.
    authority = Path(ca_file) if ca_file else next(
        iter(sorted((base / "var/lib/logsentinel-client").glob("*/receiver-ca.pem"))), None
    )
    if authority and authority != spool / "receiver-ca.pem":
        shutil.copyfile(authority, spool / "receiver-ca.pem")
        done.append("Copied the central's certificate authority from " + str(authority))
    elif not (spool / "receiver-ca.pem").exists():
        done.append("No private certificate authority found: the system authorities will be used")
    run(["chown", "-R", ACCOUNT + ":" + ACCOUNT, str(spool)])
    done.append("Spool: " + str(spool))
    write_private(base / ENV_FILE, "LOGSENTINEL_BRAIN_TOKEN=" + token + "\n", 0o600)
    done.append("Token stored for root only in " + str(base / ENV_FILE))
    write_private(base / UNIT_FILE, unit_text(receiver, machine, activity, root, executable), 0o644)
    run(["systemctl", "daemon-reload"])
    run(["systemctl", "enable", UNIT])
    run(["systemctl", "restart", UNIT])
    done.append("Service enabled and started: " + UNIT)
    if hook:
        done += install_hook(root)
    return done


def remove(root="/", run=system, purge=False):
    base = Path(root)
    done = []
    for arguments in (["systemctl", "disable", "--now", UNIT],):
        try:
            run(arguments)
            done.append("Stopped and disabled " + UNIT)
        except OSError:
            pass
    for name in (UNIT_FILE, ENV_FILE):
        path = base / name
        if path.is_file():
            path.unlink()
            done.append("Removed " + str(path))
    try:
        run(["systemctl", "daemon-reload"])
    except OSError:
        pass
    done += [line for line in remove_hook(root) if line != "Nothing to remove"]
    if purge:
        shutil.rmtree(base / SPOOL, ignore_errors=True)
        done.append("Removed the spool " + str(base / SPOOL))
        try:
            run(["userdel", ACCOUNT])
            done.append("Removed the account " + ACCOUNT)
        except OSError:
            pass
    return done or ["Nothing to remove"]
