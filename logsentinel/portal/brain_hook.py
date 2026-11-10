"""Install or remove the activity hook for the interactive shells of a host.

Recording what people type is something an administrator turns on knowingly,
so nothing installs this by itself: it is one explicit command, it says what it
wrote, and removing it is the same command with another flag.
"""

from __future__ import annotations

import os
from pathlib import Path

from .brain_collect import ACTIVITY_HOOK

HOOK = "etc/logsentinel-activity.sh"
MARK = "# logsentinel-activity"
# Login shells read profile.d; the interactive shells a terminal opens read
# these instead. A file that does not exist belongs to a shell not installed.
SHELL_FILES = ("etc/bash.bashrc", "etc/bashrc", "etc/zsh/zshrc", "etc/zshrc")
PROFILE = "etc/profile.d/logsentinel-activity.sh"


def source_line(root):
    path = Path(root) / HOOK
    return f'[ -r "{path}" ] && . "{path}"  {MARK}\n'


def write(path, text, mode=0o644):
    temp = path.with_name(path.name + ".logsentinel-new")
    temp.write_text(text)
    os.chmod(temp, mode)
    os.replace(temp, path)


def install_hook(root="/"):
    base = Path(root)
    done = []
    write(base / HOOK, ACTIVITY_HOOK)
    done.append("Wrote " + str(base / HOOK))
    line = source_line(root)
    if (base / PROFILE).parent.is_dir():
        write(base / PROFILE, line)
        done.append("Wrote " + str(base / PROFILE))
    for name in SHELL_FILES:
        path = base / name
        if not path.is_file():
            continue
        text = path.read_text(errors="replace")
        if MARK in text:
            continue
        write(path, text + ("" if text.endswith("\n") or not text else "\n") + line, path.stat().st_mode & 0o777)
        done.append("Added one line to " + str(path))
    done.append("New shells record their commands in the journal; open ones do not until restarted.")
    return done


def remove_hook(root="/"):
    base = Path(root)
    done = []
    for name in (HOOK, PROFILE):
        path = base / name
        if path.is_file():
            path.unlink()
            done.append("Removed " + str(path))
    for name in SHELL_FILES:
        path = base / name
        if not path.is_file():
            continue
        text = path.read_text(errors="replace")
        kept = "".join(l for l in text.splitlines(keepends=True) if MARK not in l)
        if kept != text:
            write(path, kept, path.stat().st_mode & 0o777)
            done.append("Removed one line from " + str(path))
    return done or ["Nothing to remove"]
