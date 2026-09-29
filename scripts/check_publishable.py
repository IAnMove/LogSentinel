"""Look for data that must not be published: personal paths, real-looking secrets, addresses.

    python scripts/check_publishable.py              # every tracked file
    python scripts/check_publishable.py --history    # also everything ever committed, on any branch

Exit status 1 when something is found. Examples and tests use synthetic data
(example.invalid, the documentation address ranges, obviously fake tokens), and
those are allowed; a path under someone's home directory, a token that looks
real, a private key body, a personal e-mail or an internal host name are not.
"""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HOME = re.compile(r"(?:/home/|/Users/)(?!user\b|USUARIO|usuario\b|example|you\b|tu\b|NAME|name\b|\$|\{|<|%)[A-Za-z_][\w.-]*/")
TOKENS = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|glpat-[A-Za-z0-9_-]{20,}|sk-[A-Za-z0-9_-]{30,}"
    r"|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{20,}|AKIA[0-9A-Z]{16}|[0-9]{8,10}:[A-Za-z0-9_-]{35})\b"
)
WEBHOOKS = re.compile(r"https://(?:hooks\.slack\.com/services/T[A-Z0-9]{6,}|(?:[\w-]+\.)?discord(?:app)?\.com/api/webhooks/\d{10,})")
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----\s*[A-Za-z0-9+/=\s]{80,}")
EMAIL = re.compile(r"\b[\w.+-]+@(?!example\.|users\.noreply\.github\.com|localhost|noreply|invalid)[\w-]+\.[a-z]{2,}\b", re.I)
INTERNAL_HOST = re.compile(r"\b(?!central\.lan|example)[a-z0-9-]+\.(?:lan|intranet|corp|localdomain)\b", re.I)
# Marked as fake by their own text.
FAKE = re.compile(r"synthetic|example|fake|dummy|placeholder|0123456789|AAAAAAAA|xxxxx|REPLACE|token-secret|1234567890|abcdefgh|s3cret|hunter", re.I)
CHECKS = (
    ("path under a personal home directory", HOME),
    ("token that looks real", TOKENS),
    ("webhook URL that looks real", WEBHOOKS),
    ("private key material", PRIVATE_KEY),
    ("e-mail address", EMAIL),
    ("internal host name", INTERNAL_HOST),
)


def scan_text(name, text):
    found = []
    for label, pattern in CHECKS:
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            # A key body is never "obviously fake": base64 of a real key has long
            # runs of A, the very pattern the fake marker looks for.
            if pattern is not PRIVATE_KEY and FAKE.search(match.group(0)):
                continue
            found.append(f"{name}:{line}: {label}: {match.group(0)[:60]!r}")
    return found


def tracked():
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [p for p in out.decode().split("\0") if p]


def scan_tree():
    found = []
    for name in tracked():
        data = (ROOT / name).read_bytes()
        if b"\0" in data[:4096]:
            continue  # binary
        found += scan_text(name, data.decode("utf-8", "replace"))
    return found


def scan_history():
    log = subprocess.run(
        ["git", "log", "--all", "-p", "--no-color", "--format=%x01%h", "--", ".", ":!*.png"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout
    found, commit = [], ""
    for line in log.splitlines():
        if line.startswith("\x01"):
            commit = line[1:]
        elif line.startswith("+") and not line.startswith("+++"):
            found += [f"commit {commit}: {item}" for item in scan_text("added line", line[1:])]
    # Say where each offending commit is published from: deleting a file does not
    # help while a branch still reaches the commit that added it.
    where = {}
    for commit in {item.split(":")[0].split()[1] for item in found}:
        branches = subprocess.run(
            ["git", "branch", "-a", "--contains", commit, "--format=%(refname:short)"],
            cwd=ROOT, capture_output=True, text=True,
        ).stdout.split()
        where[commit] = ", ".join(branches) or "no branch"
    return [f"{item}  [reachable from: {where[item.split(':')[0].split()[1]]}]" for item in found]


if __name__ == "__main__":
    issues = scan_tree() + (scan_history() if "--history" in sys.argv else [])
    print("\n".join(sorted(set(issues))) or "ok")
    sys.exit(1 if issues else 0)
