"""Nothing that identifies a real machine, person or credential may be published."""

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_publishable", ROOT / "scripts" / "check_publishable.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def in_git_checkout():
    return shutil.which("git") and subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"], cwd=ROOT, capture_output=True
    ).returncode == 0


@pytest.mark.skipif(not in_git_checkout(), reason="needs a git checkout")
def test_no_tracked_file_carries_personal_paths_secrets_or_internal_names():
    assert check.scan_tree() == []


# The samples are assembled from pieces so this file does not contain what the
# scanner looks for (it scans itself like any other tracked file).
BAD_SAMPLES = [
    "cd /home/" + "maria/proyectos/app",
    "ExecStart=/Users/" + "pedro/bin/tool",
    "token = ghp_" + "R3alLookingTokenValueKjHgFdSaPoIuYtRe12",
    "hook https://hooks." + "slack.com/services/T01ABCDEFG/B01ABCDEFG/Zx9Yw8Vv7Uu6Tt5Ss4Rr3Qq2Pp",
    "-----BEGIN OPENSSH " + "PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAABAAAAMwAAAAtzc2gtZWQyNTUxOQAAACDkTq9Lp2Xw7VbNfYhJ0RmGcU4sEoA3tZyPiWnKdLx1\nQ8vB",
    "contact maria.lopez" + "@empresa.com for access",
    "connect to nas-salon" + ".lan:8443",
]


@pytest.mark.parametrize("line", BAD_SAMPLES)
def test_the_scanner_finds_what_it_is_for(line):
    assert check.scan_text("sample.txt", line)


@pytest.mark.parametrize(
    "line",
    [
        "cd /home/user/project",
        "cd /home/USUARIO/proyecto",
        "https://central.lan:8767",
        "hooks.slack.com/services/T0/B0/token-secret",
        "Authorization: Bearer abcdef123456",
        "alice@example.com",
        "ana <216241348+IAnMove@users.noreply.github.com>",
        "203.0.113.9 port 22",
        "AKIAAAAAAAAAAAAAAAAA",
        "Path.home() / '.local'",
    ],
)
def test_synthetic_examples_are_allowed(line):
    assert check.scan_text("sample.txt", line) == []
