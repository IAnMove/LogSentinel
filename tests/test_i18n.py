"""The interface dictionary stays consistent (needs node, which CI has)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which("node"), reason="node is not installed")
def test_translations_have_no_duplicates_missing_keys_or_broken_placeholders():
    out = subprocess.run(
        ["node", str(ROOT / "scripts" / "check_i18n.js")], capture_output=True, text=True, check=True
    ).stdout
    report = json.loads(out)
    assert report["entries"] > 400
    assert report["duplicates"] == []  # a repeated key keeps only its last value
    assert report["missing"] == {}  # untranslated: English users would see Spanish
    assert report["staticMissing"] == []
    assert report["placeholders"] == []


def test_medium_severity_and_the_metrics_average_no_longer_share_a_word():
    text = (ROOT / "logsentinel" / "portal" / "static" / "i18n.js").read_text()
    assert text.count("  Media:") == 1  # severity "Medium"
    assert '  Promedio: "Average"' in text
    setup = (ROOT / "logsentinel" / "portal" / "static" / "setup.js").read_text()
    assert 'locale === "es" ? "Media" : "Medium"' not in setup  # the workaround for the clash
