"""Capture the running build once, before the source checkout can change."""

from pathlib import Path
import subprocess
import time

from logsentinel import __version__


def running_build():
    result = dict(version=__version__, commit=None, dirty=None, started=time.time())
    root = Path(__file__).resolve().parents[2]
    if (root / ".git").exists():
        try:
            result["commit"] = subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, timeout=2,
                stderr=subprocess.DEVNULL, text=True,
            ).strip()
            result["dirty"] = bool(subprocess.check_output(
                ["git", "status", "--porcelain", "--untracked-files=no"], cwd=root,
                timeout=2, stderr=subprocess.DEVNULL, text=True,
            ).strip())
        except (OSError, subprocess.SubprocessError):
            pass
    return result
