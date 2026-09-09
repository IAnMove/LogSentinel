"""Prepare a client machine so the agent reads logs without being root.

Root is needed once, here, to create an account and grant it read access. The
agent runs afterwards with nothing but that access. Every change is planned
first and printed before anything is applied, because these commands alter
permissions on files that belong to other programs.
"""

from __future__ import annotations
import grp
import os
import pwd
import subprocess
from pathlib import Path

READ_GROUP = "logsentinel-read"
JOURNAL_GROUP = "systemd-journal"
NOLOGIN = "/usr/sbin/nologin"

# Granting read access across these would hand over most of the system, which is
# the opposite of why this command exists.
FORBIDDEN = {
    Path("/"), Path("/etc"), Path("/root"), Path("/home"), Path("/boot"),
    Path("/proc"), Path("/sys"), Path("/dev"), Path("/usr"), Path("/var"),
    Path("/var/lib"), Path("/bin"), Path("/sbin"), Path("/lib"),
}


def account_exists(name):
    try:
        pwd.getpwnam(name)
        return True
    except KeyError:
        return False


def group_exists(name):
    try:
        grp.getgrnam(name)
        return True
    except KeyError:
        return False


def check_source(raw):
    """Accept a log path only if it is a real, specific place to read from."""
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise ValueError(f"Use an absolute path: {raw}")
    path = path.resolve()
    if path in FORBIDDEN:
        raise ValueError(
            f"Refusing to grant read access to {path}; name the log file or its own directory"
        )
    if not path.exists():
        raise ValueError(f"No such path: {path}")
    return path


def traversal(path):
    """Ancestor directories that do not already let everyone search through them.

    Read access on a file is useless if a directory above it refuses the walk,
    and this is the part operators most often miss. Granting search access that
    the account already had through its group is harmless and idempotent.
    """
    missing = []
    for parent in reversed(path.parents):
        if parent == Path("/"):
            continue
        try:
            if not os.stat(parent).st_mode & 0o001:
                missing.append(parent)
        except OSError:
            missing.append(parent)
    return missing


def plan(account, sources, journal=False, group=READ_GROUP):
    """Describe every change, in order, without making any of them."""
    steps = []
    if not group_exists(group):
        steps.append({
            "why": "A shared group keeps the grants revocable in one place",
            "command": ["groupadd", "--system", group],
        })
    if not account_exists(account):
        steps.append({
            "why": "A dedicated account with no login and no home of its own",
            "command": [
                "useradd", "--system", "--no-create-home",
                "--shell", NOLOGIN, "--gid", group, account,
            ],
        })
    else:
        steps.append({
            "why": f"{account} exists; make sure it is in {group}",
            "command": ["usermod", "--append", "--groups", group, account],
        })
    if journal:
        steps.append({
            "why": (
                f"Reading the whole journal means every service's messages, "
                f"including other users' — grant it only where you want that"
            ),
            "command": ["usermod", "--append", "--groups", JOURNAL_GROUP, account],
        })
    for source in sources:
        for parent in traversal(source):
            steps.append({
                "why": f"Without search access on {parent} the file below it stays unreachable",
                "command": ["setfacl", "-m", f"u:{account}:x", str(parent)],
            })
        if source.is_dir():
            steps.append({
                "why": f"Read the logs already in {source}",
                "command": ["setfacl", "-R", "-m", f"u:{account}:rX", str(source)],
            })
            steps.append({
                "why": "Keep the grant when the program writes a new file there",
                "command": ["setfacl", "-d", "-m", f"u:{account}:r", str(source)],
            })
        else:
            steps.append({
                "why": f"Read {source} without changing its owner or group",
                "command": ["setfacl", "-m", f"u:{account}:r", str(source)],
            })
    return steps


def rotation_notes(sources, account):
    """Warn where the grant will not survive on its own.

    A default ACL on the parent would carry the grant across rotation, but it
    would also grant every other file that lands in that directory later. That
    is a wider grant than the one asked for, so say so and let the operator
    choose rather than quietly widening it.
    """
    notes = []
    for source in sources:
        if source.is_dir():
            continue
        notes.append(
            f"{source} is granted as a single file. Rotation replaces it and the grant "
            f"is lost. Either grant its directory ({source.parent}) if reading everything "
            f"there is acceptable, or add a logrotate postrotate step running "
            f"setfacl -m u:{account}:r {source}."
        )
    return notes


def apply(steps, runner=subprocess.run):
    """Run the planned commands, stopping at the first refusal."""
    if os.geteuid() != 0:
        raise PermissionError("Creating accounts and setting ACLs needs root")
    done = []
    for step in steps:
        result = runner(step["command"], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"{' '.join(step['command'])} failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        done.append(step)
    return done


def verify(account, sources, journal=False, runner=subprocess.run):
    """Read as the account itself, because a granted permission is not a proven one."""
    results = []
    for source in sources:
        target = str(source)
        # A directory has to be searchable as well as readable; test has no
        # combined flag, so ask for both.
        probe = (
            ["test", "-r", target]
            if source.is_file()
            else ["test", "-r", target, "-a", "-x", target]
        )
        result = runner(
            ["runuser", "-u", account, "--", *probe], capture_output=True, text=True
        )
        results.append({"target": str(source), "readable": result.returncode == 0})
    if journal:
        result = runner(
            ["runuser", "-u", account, "--", "journalctl", "-n", "1", "--no-pager"],
            capture_output=True,
            text=True,
        )
        results.append({"target": "journal", "readable": result.returncode == 0})
    return results
