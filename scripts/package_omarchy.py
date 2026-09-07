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
    for name in files + ["docs/OMARCHY.md", "docs/QUICKSTART.en.md"]:
        path = root / name
        if path.is_symlink():
            raise ValueError("Plugin files cannot be symlinks")
        data = path.read_bytes()
        if name == "docs/OMARCHY.md":
            target = "README.md"
            data = data.replace(b"](QUICKSTART.en.md)", b"](docs/QUICKSTART.en.md)")
        else:
            target = name
        info = tarfile.TarInfo(prefix + "/" + target)
        info.mode, info.mtime, info.size = 0o644, 0, len(data)
        archive.addfile(info, io.BytesIO(data))
output = Path(args.output).expanduser().resolve()
output.parent.mkdir(parents=True, exist_ok=True)
with output.open("xb") as stream:
    stream.write(gzip.compress(buffer.getvalue(), mtime=0))
print(output)
