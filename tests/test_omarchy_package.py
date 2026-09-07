import gzip
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile


def test_plugin_bundle_is_reproducible_and_contains_no_runtime_data(tmp_path):
    root = Path(__file__).resolve().parents[1]
    paths = [tmp_path / "one.tar.gz", tmp_path / "two.tar.gz"]
    for path in paths:
        subprocess.run(
            [
                sys.executable,
                str(root / "scripts/package_omarchy.py"),
                "--output",
                str(path),
            ],
            check=True,
            capture_output=True,
        )
    assert paths[0].read_bytes() == paths[1].read_bytes()
    with tarfile.open(
        fileobj=io.BytesIO(gzip.decompress(paths[0].read_bytes()))
    ) as archive:
        entries = archive.getmembers()
        prefix = "io.github.ianmove.logsentinel/"
        assert all(
            m.isfile()
            and m.mode == 0o644
            and m.name.startswith(prefix)
            and ".." not in m.name.split("/")
            for m in entries
        )
        assert len(entries) == 7
        manifest = json.load(archive.extractfile(prefix + "manifest.json"))
        assert manifest["schemaVersion"] == 1
        assert manifest["kinds"] == ["bar-widget"]
        assert archive.extractfile(prefix + manifest["entryPoints"]["barWidget"])
        assert not any(m.name.endswith((".db", "widget.json")) for m in entries)
