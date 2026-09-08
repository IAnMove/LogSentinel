"""Read the active Omarchy desktop theme from the local machine.

No plugin or browser extension is required. The portal only looks at the
current theme directory Omarchy already maintains.
"""

from __future__ import annotations
import re
from pathlib import Path

RADIO_IDS = (
    "green",
    "daylight",
    "catppuccin",
    "catppuccin-latte",
    "ethereal",
    "everforest",
    "flexoki-light",
    "gruvbox",
    "hackerman",
    "kanagawa",
    "last-horizon",
    "lumon",
    "lupine",
    "matte-black",
    "miasma",
    "nord",
    "osaka-jade",
    "retro-82",
    "ristretto",
    "rose-pine",
    "solitude",
    "tokyo-night",
    "vantablack",
    "white",
)

COLOR_LINE = re.compile(
    r'^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*"#([0-9A-Fa-f]{6})"'
)
NAME_LINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,80}$")
COLOR_KEYS = (
    "background",
    "foreground",
    "bright_foreground",
    "accent",
    "selection",
    "red",
    "yellow",
    "blue",
)


def theme_slug(name: str) -> str:
    text = name.strip().lower().replace("_", "-")
    text = re.sub(r"^omarchy-", "", text)
    text = re.sub(r"-theme$", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:80]


def parse_colors_toml(path: Path) -> dict[str, str]:
    colors: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return colors
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("["):
            continue
        match = COLOR_LINE.match(line)
        if not match:
            continue
        key = match.group(1)
        if key in COLOR_KEYS:
            colors[key] = "#" + match.group(2).lower()
    return colors


def _read_name(path: Path) -> str:
    try:
        text = path.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except OSError:
        return ""
    return text if NAME_LINE.match(text) else ""


def detect_omarchy(home: Path | None = None) -> dict:
    """Return a JSON-safe snapshot of the desktop theme, or present=false."""
    root = Path(home) if home is not None else Path.home()
    current = root / ".config" / "omarchy" / "current"
    theme_dir = current / "theme"
    if not current.is_dir() and not theme_dir.exists():
        return {"present": False}

    name = ""
    if theme_dir.is_symlink() or theme_dir.is_dir():
        try:
            resolved = theme_dir.resolve()
            if resolved.name and resolved.name != "theme":
                name = resolved.name
        except OSError:
            name = theme_dir.name if theme_dir.name != "theme" else ""
    if not name:
        for candidate in (current / "name", theme_dir / "name"):
            name = _read_name(candidate)
            if name:
                break

    colors_path = theme_dir / "colors.toml"
    colors = parse_colors_toml(colors_path) if colors_path.is_file() else {}
    if not name and not colors and not theme_dir.exists():
        return {"present": False}

    slug = theme_slug(name) if name else ""
    matched = slug if slug in RADIO_IDS else None
    safe_name = slug or None
    return {
        "present": True,
        "name": safe_name,
        "id": matched,
        "colors": colors,
    }


def host_javascript(home: Path | None = None) -> str:
    import json

    payload = json.dumps(detect_omarchy(home), separators=(",", ":"), sort_keys=True)
    return f"window.LOGSENTINEL_OMARCHY={payload};\n"
