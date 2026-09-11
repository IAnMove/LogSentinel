"""Bounded file imports and journal polling with durable source checkpoints."""

from __future__ import annotations
import gzip
import bz2
import lzma
import hashlib
import json
import os
import shutil
import subprocess
import time
import threading
from contextlib import nullcontext
from pathlib import Path
from logsentinel.collectors.file_tailer import FileTailerCollector
from logsentinel.collectors.journald import JournaldCollector
from logsentinel.config import JournaldSourceConfig
from .store import dumps

MAX_LINE = 256_000
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
HASH_CHUNK = 1024 * 1024


def file_digest(path):
    digest = hashlib.sha256()
    with path.open("rb") as raw:
        while chunk := raw.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def discovery():
    info = {}
    try:
        for line in Path("/etc/os-release").read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                info[k] = v.strip('"')
    except OSError:
        pass
    candidates = [
        "/var/log/auth.log",
        "/var/log/syslog",
        "/var/log/secure",
        "/var/log/messages",
        "/var/log/kern.log",
    ]
    return {
        "hostname": os.uname().nodename,
        "os": info.get("PRETTY_NAME", "Linux"),
        "journalctl": bool(shutil.which("journalctl")),
        "files": [
            {"path": p, "readable": os.access(p, os.R_OK)}
            for p in candidates
            if Path(p).is_file()
        ],
    }


def normalize(line, path, origin):
    entry = FileTailerCollector.parse_log_line(line, source_path=path)
    return dict(entry.model_dump(mode="json"), origin=origin)


class Collector:
    def __init__(self, store):
        self.store = store
        self.handles = {}
        self.retired = []
        self.lock = threading.RLock()

    def close(self):
        with self.lock:
            for handle in self.handles.values():
                handle.close()
            for item in self.retired:
                item["handle"].close()
            self.handles.clear()
            self.retired.clear()

    def poll(self, source):
        with self.lock:
            return self._poll(source)

    def _poll(self, source):
        machine = self.store.get("machine", source["machine_id"])
        if (
            not source["enabled"]
            or (
                machine
                and (
                    machine.get("monitoring_paused") or machine.get("deletion_pending")
                )
            )
            or self.store.meta("deleted_machine:" + source["machine_id"])
        ):
            for key in [k for k in self.handles if k[0] == source["id"]]:
                self.handles.pop(key).close()
            for item in list(self.retired):
                if item["source"] == source["id"]:
                    item["handle"].close()
                    self.retired.remove(item)
            return 0
        total = 0
        try:
            if source["kind"] == "journald":
                total = self.journal(source)
            elif source["kind"] in ("push", "metrics", "health"):
                return 0
            else:
                root = Path(source["path"]).expanduser().resolve()
                paths = (
                    [root]
                    if source["kind"] == "file"
                    else sorted(root.glob(source["pattern"]))[:100]
                )
                if not paths:
                    raise OSError("No matching readable files")
                for path in paths:
                    if source["kind"] == "folder" and (
                        path.is_symlink() or not path.resolve().is_relative_to(root)
                    ):
                        continue
                    if path.suffix in (".gz", ".xz", ".bz2", ".zst", ".zip", ".tar"):
                        if path.is_file():
                            total += self.file(source, path)
                    elif path.is_file() or (source["id"], str(path)) in self.handles:
                        total += self.plain(source, path)
                for item in list(self.retired):
                    if item["source"] != source["id"]:
                        continue
                    total += self.file(
                        source,
                        item["path"],
                        handle=item["handle"],
                        cursor_key=item["key"],
                    )
                    size = os.fstat(item["handle"].fileno()).st_size
                    if size != item["size"]:
                        item.update(size=size, quiet=time.monotonic())
                    if time.monotonic() - item["quiet"] > 300:
                        item["handle"].close()
                        self.retired.remove(item)
                        self.store.metric(source["id"], "rotation_watch_closed", 1)
            self.store.set_meta(
                "health:" + source["id"],
                dumps({"status": "ok", "checked": time.time(), "new_events": total}),
            )
        except Exception as exc:
            self.store.set_meta(
                "health:" + source["id"],
                dumps(
                    {"status": "error", "checked": time.time(), "error": str(exc)[:300]}
                ),
            )
        return total

    def plain(self, source, path):
        key = (source["id"], str(path))
        handle = self.handles.get(key)
        try:
            current = path.stat()
        except FileNotFoundError:
            current = None
        if handle and current:
            previous = os.fstat(handle.fileno())
            if (previous.st_dev, previous.st_ino) != (current.st_dev, current.st_ino):
                retired_key = (
                    str(path)
                    + "#rotated:"
                    + str(previous.st_dev)
                    + ":"
                    + str(previous.st_ino)
                )
                cursor = self.store.cursor(source["id"], str(path))
                if cursor:
                    self.store.ingest(source, [], retired_key, cursor)
                self.retired.append(
                    {
                        "source": source["id"],
                        "path": path,
                        "key": retired_key,
                        "handle": handle,
                        "size": previous.st_size,
                        "quiet": time.monotonic(),
                    }
                )
                del self.handles[key]
                handle = None
        if handle is None:
            if current is None:
                return 0
            if len(self.handles) + len(self.retired) >= 128:
                raise OSError(
                    "Open source/rotation handle limit reached; reduce sources or rotation frequency"
                )
            handle = path.open("rb")
            self.handles[key] = handle
        return self.file(source, path, handle=handle)

    def file(self, source, path, handle=None, cursor_key=None):
        stat = os.fstat(handle.fileno()) if handle else path.stat()
        key = cursor_key or str(path)
        old = self.store.cursor(source["id"], key) or {}
        sig = [stat.st_dev, stat.st_ino]
        offset = 0
        if not old:
            with self.store.connect() as db:
                for row in db.execute(
                    "SELECT data FROM cursors WHERE source_id=?", (source["id"],)
                ):
                    candidate = json.loads(row[0])
                    if candidate.get("identity") == sig:
                        old = candidate
                        break
        if path.suffix in (".zst", ".zip", ".tar"):
            raise ValueError("Unsupported archive; supply plain text, gzip, xz or bz2")
        compressed = path.suffix in (".gz", ".xz", ".bz2")
        if compressed:
            stamp = [stat.st_size, stat.st_mtime_ns]
            if old.get("stamp") != stamp:
                self.store.ingest(source, [], key, {"stamp": stamp, "stable": False})
                return 0
            if old.get("done"):
                return 0
            # A new archive is imported only after an unchanged polling interval.
            if stat.st_size > MAX_ARCHIVE_BYTES:
                raise ValueError("Archive exceeds 64 MiB input limit")
            digest = old.get("digest") or file_digest(path)
            generation = "gz:" + digest
            offset = old.get("offset", 0)
            if offset >= MAX_EXPANDED_BYTES:
                self.store.ingest(
                    source,
                    [],
                    key,
                    dict(old, stamp=stamp, stable=True, done=True, digest=digest),
                )
                return 0
            opener = {".gz": gzip.open, ".xz": lzma.open, ".bz2": bz2.open}[path.suffix]
        else:
            generation = old.get(
                "generation", f"{stat.st_dev}:{stat.st_ino}:{stat.st_ctime_ns}"
            )
            opener = (lambda *args: nullcontext(handle)) if handle else open
            if old.get("identity") == sig and stat.st_size >= old.get("offset", 0):
                offset = old.get("offset", 0)
                with opener(path, "rb") as f:
                    f.seek(max(0, offset - 64))
                    check = f.read(min(64, offset))
                if hashlib.sha256(check).hexdigest() != old.get(
                    "tail", hashlib.sha256(b"").hexdigest()
                ):
                    offset = 0
                    generation = f"{stat.st_dev}:{stat.st_ino}:{stat.st_ctime_ns}"
            elif old:
                generation = f"{stat.st_dev}:{stat.st_ino}:{stat.st_ctime_ns}"
            elif not source.get("history"):
                offset = stat.st_size
        entries = []
        used = 0
        done = False
        with opener(path, "rb") as f:
            f.seek(offset)
            while used < source["max_batch_bytes"] and len(entries) < 1000:
                begin = f.tell()
                if compressed and begin >= MAX_EXPANDED_BYTES:
                    done = True
                    break
                line = f.readline(MAX_LINE + 1)
                if not line:
                    done = True
                    break
                if len(line) > MAX_LINE:
                    raise ValueError(
                        "Event exceeds 256 KB; change source format or explicit source limit policy"
                    )
                if compressed and begin + len(line) > MAX_EXPANDED_BYTES:
                    done = True
                    f.seek(begin)
                    break
                if not line.endswith(b"\n") and not compressed:
                    f.seek(begin)
                    break
                text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                if source.get("multiline") and text.startswith((" ", "\t")) and entries:
                    entries[-1]["message"] += "\n" + text
                    entries[-1]["raw"] += "\n" + text
                elif text:
                    entries.append(normalize(text, key, f"{generation}:{begin}"))
                used += len(line)
            end = f.tell()
            tail = ""
            if not compressed:
                f.seek(max(0, end - 64))
                tail = hashlib.sha256(f.read(min(64, end))).hexdigest()
        cursor = {
            "identity": sig,
            "generation": generation,
            "offset": end,
            "tail": tail,
        }
        if compressed:
            cursor.update(stamp=stamp, stable=True, done=done, digest=digest)
        count = self.store.ingest(source, entries, key, cursor)
        self.store.metric(source["id"], "read_bytes", used)
        return count

    def journal(self, source):
        cursor = self.store.cursor(source["id"], "journal") or {}
        cmd = ["journalctl", "--no-pager", "-o", "json"]
        if cursor.get("cursor"):
            cmd += ["--after-cursor", cursor["cursor"]]
        elif not source.get("history"):
            cmd += ["-n", "1"]
        # Timeout/output bounded using a temporary spool, not communicate on unlimited output.
        import tempfile

        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as err:
            proc = subprocess.Popen(cmd, stdout=output, stderr=err)
            deadline = time.monotonic() + 3
            while (
                proc.poll() is None
                and time.monotonic() < deadline
                and output.tell() < source["max_batch_bytes"]
            ):
                time.sleep(0.02)
            if proc.poll() is None:
                proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            if proc.returncode not in (0, -15):
                raise OSError("journalctl failed; check journal permissions/cursor")
            output.seek(0)
            raw = output.read(source["max_batch_bytes"])
        collector = JournaldCollector(JournaldSourceConfig())
        entries = []
        last = None
        skipped = 0
        for line in raw.splitlines(keepends=True):
            if not line.endswith(b"\n"):
                break
            text = line.decode("utf-8", errors="replace")
            try:
                data = json.loads(text)
            except (json.JSONDecodeError, TypeError, ValueError):
                skipped += 1
                continue
            if not isinstance(data, dict):
                skipped += 1
                continue
            mark = data.get("__CURSOR")
            if not isinstance(mark, str) or not mark:
                skipped += 1
                continue
            last = mark
            e = collector._parse_json_line(text)
            if e:
                entries.append(
                    dict(e.model_dump(mode="json"), origin="journal:" + last)
                )
        if skipped:
            self.store.metric(source["id"], "journal_skipped", skipped)
        if last:
            if not cursor and not source.get("history"):
                entries = []
            return self.store.ingest(source, entries, "journal", {"cursor": last})
        return 0
