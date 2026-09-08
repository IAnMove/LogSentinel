from pathlib import Path
from logsentinel.portal.app import create_app
from logsentinel.portal.omarchy_detect import detect_omarchy, host_javascript, theme_slug


def write_theme(home: Path, name: str, colors: str) -> Path:
    theme = home / ".config" / "omarchy" / "current" / "theme"
    theme.mkdir(parents=True)
    (theme / "colors.toml").write_text(colors, encoding="utf-8")
    (home / ".config" / "omarchy" / "current" / "name").write_text(
        name + "\n", encoding="utf-8"
    )
    return theme


def test_theme_slug_normalizes_omarchy_install_names():
    assert theme_slug("Tokyo Night") == "tokyo-night"
    assert theme_slug("omarchy-rose-pine-theme") == "rose-pine"
    assert theme_slug("catppuccin_latte") == "catppuccin-latte"


def test_absent_home_is_not_omarchy(tmp_path):
    assert detect_omarchy(tmp_path) == {"present": False}


def test_named_omarchy_theme_is_compatible(tmp_path):
    write_theme(
        tmp_path,
        "tokyo-night",
        'background = "#1a1b26"\naccent = "#7aa2f7"\nforeground = "#c0caf5"\n',
    )
    found = detect_omarchy(tmp_path)
    assert found["present"] is True
    assert found["id"] == "tokyo-night"
    assert found["name"] == "tokyo-night"
    assert found["colors"]["background"] == "#1a1b26"
    assert found["colors"]["accent"] == "#7aa2f7"
    script = host_javascript(tmp_path)
    assert script.startswith("window.LOGSENTINEL_OMARCHY=")
    assert "/home/" not in script
    assert "tmp" not in script.lower() or "tokyo-night" in script


def test_unknown_theme_keeps_colors_without_claiming_a_radio_id(tmp_path):
    write_theme(
        tmp_path,
        "my-custom-theme",
        'background = "#101010"\naccent = "#ff00aa"\nforeground = "#eeeeee"\n',
    )
    found = detect_omarchy(tmp_path)
    assert found["present"] is True
    assert found["id"] is None
    assert found["colors"]["accent"] == "#ff00aa"


def test_host_script_is_public_and_has_no_paths(tmp_path):
    html = Path("logsentinel/portal/static/index.html").read_text(encoding="utf-8")
    assert 'src="/omarchy-host.js"' in html
    script = host_javascript(tmp_path)
    assert script.startswith("window.LOGSENTINEL_OMARCHY=")
    assert '"present":false' in script.replace(" ", "")
    app = create_app(tmp_path, background=False)
    routes = {getattr(route, "path", "") for route in app.routes}
    assert "/omarchy-host.js" in routes
