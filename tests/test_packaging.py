"""One version, coherent metadata, and shell entry points that survive a checkout."""

import json
import re
from pathlib import Path

import pytest

import logsentinel

ROOT = Path(__file__).resolve().parents[1]


def pyproject():
    return (ROOT / "pyproject.toml").read_text()


def test_every_place_that_states_a_version_states_the_same_one():
    declared = re.search(r'(?m)^version = "([^"]+)"', pyproject()).group(1)
    manifest = json.loads((ROOT / "manifest.json").read_text())["version"]
    assert logsentinel.__version__ == declared == manifest


def test_the_license_expression_is_supported_by_the_declared_build_backend():
    text = pyproject()
    assert re.search(r'(?m)^license = "[A-Za-z0-9.+-]+"', text)  # an SPDX string
    floor = re.search(r'requires = \["setuptools>=(\d+)', text)
    assert floor and int(floor.group(1)) >= 77


def test_direct_third_party_imports_are_declared_dependencies():
    text = pyproject()
    declared = {m.lower() for m in re.findall(r'(?m)^\s+"([A-Za-z0-9_.-]+)[<>=!~ ]', text.split("dependencies = [")[1].split("]")[0])}
    imported = set()
    for path in (ROOT / "logsentinel").rglob("*.py"):
        for match in re.finditer(r"(?m)^\s*(?:from|import) ([a-z_][a-z0-9_]*)", path.read_text()):
            imported.add(match.group(1))
    third_party = {"httpx", "httpcore", "fastapi", "starlette", "anyio", "pydantic", "yaml", "regex", "typer", "rich", "uvicorn"}
    names = {"yaml": "pyyaml"}
    for module in imported & third_party:
        assert names.get(module, module) in declared, module


def test_dependencies_have_an_upper_bound():
    block = pyproject().split("dependencies = [")[1].split("]")[0]
    for line in re.findall(r'(?m)^\s+"([^"]+)"', block):
        name = re.match(r"[A-Za-z0-9_.-]+", line).group(0)
        if name == "regex":
            continue  # calendar versioned
        assert "<" in line, line


@pytest.mark.parametrize("name", ["portal", "plugin", "setup-client.sh"])
def test_shell_entry_points_keep_unix_line_endings_and_are_executable(name):
    assert b"\r" not in (ROOT / name).read_bytes()
    assert (ROOT / name).stat().st_mode & 0o111
    assert re.search(rf"(?m)^{re.escape(name)} text eol=lf$", (ROOT / ".gitattributes").read_text())


def test_the_source_tree_ships_every_file_the_page_refers_to():
    import importlib.util

    spec = importlib.util.spec_from_file_location("check_wheel", ROOT / "scripts" / "check_wheel.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.from_tree() == []
    broken = module.problems(
        {"logsentinel/portal/static/index.html", "logsentinel/tests/x.py"},
        lambda name: b'<script src="/static/missing.js"></script>',
    )
    assert any("missing.js" in line for line in broken)
    assert any("does not belong" in line for line in broken)
    assert any("missing from the package" in line for line in broken)


def test_the_checked_in_unit_uses_the_same_hardening_as_the_generated_one():
    from logsentinel.cli import SERVICE_HARDENING

    generated = set(SERVICE_HARDENING.splitlines())
    shipped = {
        line
        for line in (ROOT / "systemd" / "logsentinel-portal.service").read_text().splitlines()
        if "=" in line and line.split("=")[0] not in {
            "Description", "After", "Type", "ExecStart", "Restart", "RestartSec", "ReadWritePaths", "WantedBy",
        }
    }
    assert shipped == generated, (shipped ^ generated)


def _luminance(colour):
    channels = [int(colour.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a, b):
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_the_muted_text_colour_of_every_light_theme_reads_on_its_own_backgrounds():
    """WCAG AA asks 4.5:1 for normal text; muted text on the page and on panels is normal text."""
    css = (ROOT / "logsentinel" / "portal" / "static" / "themes.css").read_text()
    themes = re.findall(r'(?:\[data-palette="(\w+)"\]|:root\[data-theme="(\w+)"\])[^{]*\{([^}]*)\}', css)
    checked = 0
    for a, b, body in themes:
        values = dict(re.findall(r"--(bg|surface|muted|soft):\s*(#[0-9a-fA-F]{6})\b", body))
        if "muted" not in values or "bg" not in values:
            continue
        for background in ("bg", "surface", "soft"):
            if background in values:
                assert _contrast(values["muted"], values[background]) >= 4.5, (a or b, background)
                checked += 1
    assert checked >= 4
