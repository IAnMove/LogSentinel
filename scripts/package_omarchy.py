"""Build an explicit, reproducible plugin-only bundle; never include user data."""

import argparse
import gzip
import io
import json
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", required=True)
args = parser.parse_args()
manifest = json.loads((root / "manifest.json").read_text())
prefix = manifest["id"]
files = [
    "manifest.json",
    "LICENSE",
    "integrations/omarchy/SentinelWidget.qml",
    "integrations/omarchy/SentinelPanel.qml",
    "integrations/omarchy/Status.js",
]
buffer = io.BytesIO()
with tarfile.open(fileobj=buffer, mode="w") as archive:
    guides = [
        "docs/OMARCHY.md",
        "docs/QUICKSTART.en.md",
        "docs/METRICS.md",
        "docs/OPERATIONS.md",
        "docs/PROBLEM_INVESTIGATIONS.md",
        "docs/THEMES.md",
    ]
    for name in files + guides:
        path = root / name
        if path.is_symlink():
            raise ValueError("Plugin files cannot be symlinks")
        data = path.read_bytes()
        if name == "docs/QUICKSTART.en.md":
            data = data.replace(
                b"](REVIEW_2026-09-07.md)",
                b"](https://github.com/IAnMove/LogSentinel/blob/main/docs/REVIEW_2026-09-07.md)",
            )
        info = tarfile.TarInfo(prefix + "/" + name)
        info.mode, info.mtime, info.size = 0o644, 0, len(data)
        archive.addfile(info, io.BytesIO(data))
    data = b"# LogSentinel for Omarchy\n\nSee [installation, pairing, controls and removal](docs/OMARCHY.md).\n\nRequires Omarchy Quattro, curl and a separately installed LogSentinel portal.\nThe widget uses a revocable, read-only credential. No install hooks or elevated privileges.\n\nPrepared for on-desktop validation before publication; see the guide for current limitations.\n"
    info = tarfile.TarInfo(prefix + "/README.md")
    info.mode, info.mtime, info.size = 0o644, 0, len(data)
    archive.addfile(info, io.BytesIO(data))
output = Path(args.output).expanduser().resolve()
output.parent.mkdir(parents=True, exist_ok=True)
with output.open("xb") as stream:
    stream.write(gzip.compress(buffer.getvalue(), mtime=0))
print(output)
