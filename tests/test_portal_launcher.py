from pathlib import Path


def test_linux_portal_wrapper_installs_venv_and_starts_portal():
    script = Path(__file__).resolve().parents[1] / "portal"
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "python3 -m venv" in text
    assert "pip install" in text
    assert 'exec "$venv/bin/logsentinel" portal "$@"' in text


def test_omarchy_plugin_wrapper_refuses_non_omarchy_and_does_not_publish():
    script = Path(__file__).resolve().parents[1] / "plugin"
    text = script.read_text(encoding="utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "omarchy plugin list" in text
    assert "not_omarchy" in text
    assert "marketplace" in text.lower()
    assert "io.github.ianmove.logsentinel" in text
    assert "plugin add https://" not in text
    enable_at = text.find("omarchy plugin enable")
    rescan_at = text.find("rescanPlugins")
    assert rescan_at != -1 and enable_at != -1 and rescan_at < enable_at
