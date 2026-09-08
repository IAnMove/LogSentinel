from pathlib import Path


def test_linux_portal_wrapper_installs_venv_and_starts_portal():
    script = Path(__file__).resolve().parents[1] / "portal"
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "python3 -m venv" in text
    assert "pip install" in text
    assert 'exec "$venv/bin/logsentinel" portal "$@"' in text
