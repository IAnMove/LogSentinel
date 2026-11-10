"""What a machine has installed and what was typed on it, read on that machine.

Two kinds of record leave here. An inventory is a picture of the host (system,
packages, enabled services, listening ports, accounts); the central compares
each one with the last and keeps the differences. An activity record is one
interactive shell command with the directory and the project it was run in, so
that "which machine did I do that on" has an answer weeks later.

Nothing here needs root. The inventory uses what any account may read. The
commands arrive through the journal: a shell hook (ACTIVITY_HOOK, installed by
an administrator, off unless installed) writes each one there, and the journal
itself records which user wrote it. Command lines carry secrets, so they are
redacted before they are stored anywhere.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import pwd
import subprocess
import time
from pathlib import Path

from logsentinel.collectors.journald import PRIVATE_IDENTIFIER as IDENTIFIER
from logsentinel.redact import redact

MAX_COMMAND = 2000
MAX_PATH = 500
# Bounds on one inventory: a host with more than this is cut, and says so.
MAX_ITEMS = {"packages": 20000, "services": 3000, "ports": 2000, "users": 2000}
CATEGORIES = ("system", "packages", "services", "ports", "users")
NO_LOGIN = ("nologin", "false", "sync", "shutdown", "halt")
ADMIN_GROUPS = ("sudo", "wheel", "admin")

# Sourced by interactive bash and zsh shells. It writes through the journal's
# native protocol so the fields stay separate and the journal stamps the
# writer's uid itself; the text of a command cannot claim another user.
# A command typed with a leading space is not recorded by bash when HISTCONTROL
# ignores it, and is skipped explicitly under zsh: the same habit that keeps a
# command out of the history keeps it out of here.
ACTIVITY_HOOK = r"""# LogSentinel activity hook: records interactive commands in the journal.
# Remove this file (and the lines that source it) to stop recording.
if [ -z "${__logsentinel_activity:-}" ] && command -v logger >/dev/null 2>&1; then
  __logsentinel_activity=1
  __logsentinel_send() {
    # $1 command, already on one line
    local p="$PWD"
    while [ -n "$p" ] && [ ! -e "$p/.git" ]; do p="${p%/*}"; done
    printf 'MESSAGE=%s\nSYSLOG_IDENTIFIER=logsentinel-activity\nPRIORITY=6\nLS_CWD=%s\nLS_PROJECT=%s\n' \
      "$1" "$PWD" "${p##*/}" | logger --journald 2>/dev/null
  }
  if [ -n "${BASH_VERSION:-}" ] && [ -n "${PS1:-}" ]; then
    __logsentinel_number() {
      local line
      line="$(HISTTIMEFORMAT='' builtin history 1 2>/dev/null)"
      line="${line#"${line%%[![:space:]]*}"}"
      printf '%s' "${line%%[[:space:]]*}"
    }
    __logsentinel_last="$(__logsentinel_number)"
    __logsentinel_prompt() {
      local line number
      line="$(HISTTIMEFORMAT='' builtin history 1 2>/dev/null)"
      line="${line#"${line%%[![:space:]]*}"}"
      number="${line%%[[:space:]]*}"
      [ -n "$number" ] && [ "$number" != "$__logsentinel_last" ] || return 0
      __logsentinel_last="$number"
      line="${line#*[[:space:]]}"
      line="${line#"${line%%[![:space:]]*}"}"
      line="${line//$'\n'/ ; }"
      [ -n "$line" ] && __logsentinel_send "$line"
      return 0
    }
    PROMPT_COMMAND="__logsentinel_prompt${PROMPT_COMMAND:+;$PROMPT_COMMAND}"
  elif [ -n "${ZSH_VERSION:-}" ] && [[ -o interactive ]]; then
    __logsentinel_preexec() {
      case "$1" in ' '*|'') return 0 ;; esac
      __logsentinel_send "${1//$'\n'/ ; }"
    }
    autoload -Uz add-zsh-hook 2>/dev/null && add-zsh-hook preexec __logsentinel_preexec
  fi
fi
"""


def run(arguments, timeout=30):
    """Output lines of a read-only command, or None when it is not there."""
    try:
        done = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            env=dict(os.environ, LC_ALL="C", LANG="C"),
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode:
        return None
    return done.stdout.splitlines()


def packages():
    lines = run(["dpkg-query", "-W", "-f", "${Package}\t${Version}\t${db:Status-Abbrev}\n"])
    if lines is not None:
        found = {}
        for line in lines:
            parts = line.split("\t")
            if len(parts) == 3 and parts[2].startswith("ii"):
                found[parts[0]] = parts[1]
        return found
    lines = run(["rpm", "-qa", "--qf", "%{NAME}\t%{VERSION}-%{RELEASE}\n"])
    if lines is None:
        lines = run(["pacman", "-Q"])
        if lines is not None:
            lines = [line.replace(" ", "\t", 1) for line in lines]
    if lines is None:
        return None
    return dict(line.split("\t", 1) for line in lines if "\t" in line)


def services():
    lines = run(
        ["systemctl", "list-unit-files", "--type=service", "--state=enabled", "--no-legend", "--plain"]
    )
    if lines is None:
        return None
    return {line.split()[0]: "enabled" for line in lines if line.split()}


def ports():
    lines = run(["ss", "-H", "-ltun"])
    if lines is None:
        return None
    found = {}
    for line in lines:
        parts = line.split()
        # netid state recv-q send-q local peer
        if len(parts) >= 5:
            found[parts[0] + " " + parts[4]] = "listening"
    return found


def users(root="/"):
    found = {}
    try:
        for line in (Path(root) / "etc/passwd").read_text(errors="replace").splitlines():
            parts = line.split(":")
            if len(parts) >= 7 and parts[6].rsplit("/", 1)[-1] not in NO_LOGIN:
                found[parts[0]] = "uid " + parts[2] + ", " + parts[6]
        for line in (Path(root) / "etc/group").read_text(errors="replace").splitlines():
            parts = line.split(":")
            if len(parts) >= 4 and parts[0] in ADMIN_GROUPS and parts[3]:
                found["group " + parts[0]] = parts[3]
    except OSError:
        return None
    return found


def system(root="/"):
    name = ""
    try:
        for line in (Path(root) / "etc/os-release").read_text(errors="replace").splitlines():
            if line.startswith("PRETTY_NAME="):
                name = line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    uname = platform.uname()
    return dict(os=name, kernel=uname.release, architecture=uname.machine, hostname=uname.node)


def inventory(now=None):
    """One picture of this host. A reader that fails is named, not guessed."""
    observed = time.time() if now is None else now
    data: dict = {"system": system()}
    errors = []
    for category, reader in (
        ("packages", packages),
        ("services", services),
        ("ports", ports),
        ("users", users),
    ):
        found = reader()
        if found is None:
            errors.append(category)
            continue
        limit = MAX_ITEMS[category]
        if len(found) > limit:
            errors.append(category + "_truncated")
            found = dict(sorted(found.items())[:limit])
        data[category] = {str(k)[:300]: str(v)[:300] for k, v in found.items()}
    body = json.dumps(data, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(body.encode()).hexdigest()
    return dict(
        id="inv-" + str(int(observed)) + "-" + digest[:12],
        kind="inventory",
        observed=observed,
        digest=digest,
        data=data,
        errors=errors,
    )


def user_name(uid):
    try:
        return pwd.getpwuid(int(uid)).pw_name
    except (KeyError, ValueError, TypeError):
        return "uid " + str(uid)[:12]


def text(value):
    """A journal field as text; journald gives non-UTF-8 values as byte lists."""
    if isinstance(value, list):
        try:
            return bytes(value).decode("utf-8", "replace")
        except (ValueError, TypeError):
            return ""
    return value if isinstance(value, str) else ""


def activity_record(entry):
    """A journal entry written by the hook, as a redacted activity record."""
    command = text(entry.get("MESSAGE")).strip()
    cursor = text(entry.get("__CURSOR"))
    try:
        observed = int(entry.get("__REALTIME_TIMESTAMP")) / 1_000_000
    except (TypeError, ValueError):
        return None
    if not command or not cursor:
        return None
    return dict(
        id="cmd-" + hashlib.sha256(cursor.encode()).hexdigest()[:24],
        kind="command",
        observed=observed,
        user=user_name(entry.get("_UID"))[:64],
        cwd=text(entry.get("LS_CWD"))[:MAX_PATH],
        project=text(entry.get("LS_PROJECT"))[:120],
        command=redact(command)[:MAX_COMMAND],
    )


def read_activity(cursor="", limit=2000, since_seconds=86400):
    """Commands the hook has written since the cursor: (records, new cursor).

    A cursor the journal no longer has (rotation) falls back to the recent
    window instead of failing for ever; the ids make a repeat harmless."""
    # Oldest first and cut here: journalctl's own -n keeps the newest lines,
    # which would skip whatever came right after the cursor.
    base = ["journalctl", "-t", IDENTIFIER, "-o", "json", "--no-pager"]
    lines = None
    if cursor:
        lines = run(base + ["--after-cursor", cursor])
    if lines is None:
        lines = run(base + ["--since", "-" + str(int(since_seconds)) + "s"])
    if lines is None:
        raise OSError("Cannot read the journal; the account needs the systemd-journal group")
    records = []
    last = cursor
    for line in lines[:limit]:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        last = text(entry.get("__CURSOR")) or last
        record = activity_record(entry)
        if record:
            records.append(record)
    return records, last
