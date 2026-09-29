"""Check that a built wheel (or the source tree) carries everything the portal serves.

    python scripts/check_wheel.py path/to/logsentinel-*.whl
    python scripts/check_wheel.py            # the source tree, as the tests do

Fails when a page, script or stylesheet refers to a static file that is not
packaged, when the route modules are missing, or when development files ended
up in the package.
"""

import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = "logsentinel/portal/static/"
REQUIRED = (
    "logsentinel/cli.py",
    "logsentinel/portal/app.py",
    "logsentinel/portal/routes/__init__.py",
    "logsentinel/portal/routes/objects.py",
    STATIC + "index.html",
    STATIC + "app.js",
    STATIC + "style.css",
)
FORBIDDEN = re.compile(r"(^|/)(tests?|\.venv|__pycache__|\.git)(/|$)|\.pyc$|(^|/)\.env")
REFERENCE = re.compile(r"""["'(=]\s*/static/([A-Za-z0-9][A-Za-z0-9._-]*\.[A-Za-z0-9]+)""")


def problems(names, read):
    names = set(names)
    found = [f"missing from the package: {path}" for path in REQUIRED if path not in names]
    found += [f"does not belong in the package: {name}" for name in sorted(names) if FORBIDDEN.search(name)]
    for name in sorted(names):
        if name.startswith(STATIC) and name.endswith((".html", ".js", ".css")):
            text = read(name).decode("utf-8", "replace")
            for target in sorted(set(REFERENCE.findall(text))):
                if STATIC + target not in names:
                    found.append(f"{name} refers to /static/{target}, which is not packaged")
    return found


def from_wheel(path):
    with zipfile.ZipFile(path) as wheel:
        names = [n for n in wheel.namelist() if n.startswith("logsentinel/")]
        return problems(names, wheel.read)


def from_tree(root=ROOT):
    names = [
        str(p.relative_to(root))
        for p in (root / "logsentinel").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts
    ]
    return problems(names, lambda name: (root / name).read_bytes())


if __name__ == "__main__":
    issues = from_wheel(sys.argv[1]) if len(sys.argv) > 1 else from_tree()
    print("\n".join(issues) or "ok")
    sys.exit(1 if issues else 0)
