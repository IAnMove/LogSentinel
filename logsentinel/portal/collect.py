"""Bounded file imports and journal polling with durable source checkpoints."""

from __future__ import annotations
import gzip
import io
import bz2
import lzma
import zlib
import hashlib
import json
import os
import shutil
import time
import threading
from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .journal_stream import read_journal
from .logs import report
from contextlib import nullcontext
from pathlib import Path
import httpx
from logsentinel.collectors.file_tailer import FileTailerCollector
from logsentinel.collectors.journald import JournaldCollector
from logsentinel.config import JournaldSourceConfig
from .store import dumps
from .web_access import WEB_SERVICE, parse_access_line
from .source_paths import open_source, validate_source_handle, validate_source_path, UnsafeSourcePath

MAX_LINE = 256_000
MAX_FOLDER_FILES = 100
# An xz header can ask the decoder for a gigabyte of dictionary; an archive that
# needs more than this to be read is refused rather than allowed to exhaust memory.
XZ_MEMORY_LIMIT = 128 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 128 * 1024 * 1024
HASH_CHUNK = 1024 * 1024


class LimitedXZ(io.RawIOBase):
    """Read an xz file through decoders with a memory ceiling, seekably.

    lzma.LZMAFile has no such limit; LZMADecompressor does. Like LZMAFile this
    reads concatenated streams and supports seek (backwards by starting over)."""

    def __init__(self, raw):
        self.raw = raw
        self.position = 0
        self._restart()

    def _restart(self):
        self.raw.seek(0)
        self.decoder = lzma.LZMADecompressor(memlimit=XZ_MEMORY_LIMIT)
        self.pending = b""
        self.position = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=io.SEEK_SET):
        if whence != io.SEEK_SET:
            raise io.UnsupportedOperation("only absolute seeks are supported")
        if offset < self.position:
            self._restart()
        while self.position < offset:
            if not self.read(min(1 << 20, offset - self.position)):
                break
        return self.position

    def readinto(self, buffer):
        while not self.pending:
            if self.decoder.eof:
                # A finished stream may be followed by zero padding and another
                # stream; only a clean end of the file ends the data.
                rest = self.decoder.unused_data
                while not rest.strip(b"\0"):
                    rest = self.raw.read(64 * 1024)
                    if not rest:
                        return 0
                self.decoder = lzma.LZMADecompressor(memlimit=XZ_MEMORY_LIMIT)
                chunk = rest.lstrip(b"\0")
            elif self.decoder.needs_input:
                chunk = self.raw.read(64 * 1024)
                if not chunk:
                    raise EOFError("Compressed file ended before the end-of-stream marker")
            else:
                chunk = b""
            self.pending = self.decoder.decompress(chunk, max_length=len(buffer))
        n = min(len(buffer), len(self.pending))
        buffer[:n] = self.pending[:n]
        self.pending = self.pending[n:]
        self.position += n
        return n


def open_xz(handle):
    handle.seek(0)
    return io.BufferedReader(LimitedXZ(handle))


def file_digest(path, handle=None):
    digest = hashlib.sha256()
    with nullcontext(handle) if handle else path.open("rb") as raw:
        raw.seek(0)
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
    llm = []
    for provider, url, path in (
        ("ollama", "http://127.0.0.1:11434", "/api/tags"),
        ("llama.cpp", "http://127.0.0.1:8081", "/v1/models"),
        ("llama.cpp", "http://127.0.0.1:8080", "/v1/models"),
    ):
        try:
            with httpx.Client(
                timeout=0.4, trust_env=False, follow_redirects=False
            ) as client:
                response = client.get(url + path)
            if (
                response.is_success
                and "json" in response.headers.get("content-type", "").lower()
            ):
                llm.append({"provider": provider, "base_url": url, "reachable": True})
        except httpx.HTTPError:
            continue
    return {
        "hostname": os.uname().nodename,
        "os": info.get("PRETTY_NAME", "Linux"),
        "llm": llm,
        "journalctl": bool(shutil.which("journalctl")),
        "files": [
            {"path": p, "readable": os.access(p, os.R_OK)}
            for p in candidates
            if Path(p).is_file()
        ],
    }


def machine_zone(store, source):
    """Timezone of the machine that wrote a source, for lines that carry none."""
    machine = store.get("machine", source["machine_id"]) or {}
    try:
        return ZoneInfo(machine.get("timezone") or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def fit_line(text, dropped):
    """A line cut at the limit, ending in a note that says so and how much went.

    The note is part of the stored text so that anyone reading the event, or the
    evidence of a problem, sees it was cut. The result still fits MAX_LINE once
    encoded: bytes that were not valid UTF-8 grow when they are replaced.
    """
    note = f" ... [line cut: about {dropped} more bytes were not stored]"
    room = MAX_LINE - len(note.encode()) - 8
    while len(text.encode()) > room:
        text = text[: max(1, int(len(text) * 0.9))]
    return text + note


def normalize(line, path, origin, tz=None):
    entry = FileTailerCollector.parse_log_line(line, source_path=path, tz=tz)
    # Read the message, not the raw line, so access lines forwarded through
    # syslog (nginx and Apache can log there) are recognised as well.
    request = parse_access_line(entry.message)
    if request:
        # Date the event by the server's own clock. Reading a line now says
        # nothing about when it happened: a history import or a catch-up after
        # downtime would otherwise date every request "now".
        entry = entry.model_copy(
            update=dict(
                timestamp=request.time,
                service=WEB_SERVICE,
                metadata=dict(entry.metadata, timestamp_inferred=False, web=request.fields()),
            )
        )
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

    def poll(self, source, strict=False):
        with self.lock:
            return self._poll(source, strict)

    def _poll(self, source, strict=False):
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
                root = validate_source_path(source["path"], self.store.directory)
                skipped = 0
                if source["kind"] == "file":
                    paths = [root]
                else:
                    matches = self.newest_first(root, source["pattern"])
                    paths, skipped = matches[:MAX_FOLDER_FILES], max(0, len(matches) - MAX_FOLDER_FILES)
                if not paths:
                    raise OSError("No matching readable files")
                failures = []
                for path in paths:
                    if source["kind"] == "folder" and (
                        path.is_symlink() or not path.resolve().is_relative_to(root)
                    ):
                        continue
                    try:
                        validate_source_path(path, self.store.directory)
                        if path.suffix in (".gz", ".xz", ".bz2", ".zst", ".zip", ".tar"):
                            if path.is_file():
                                total += self.file(source, path)
                        elif path.is_file() or (source["id"], str(path)) in self.handles:
                            total += self.plain(source, path)
                    except UnsafeSourcePath:
                        self.store.metric(source["id"], "blocked_source_files", 1)
                        continue
                    except Exception as exc:
                        # One unreadable file must not stop the ones after it.
                        if strict or source["kind"] == "file":
                            raise
                        failures.append((path.name, str(exc)[:100]))
                        self.store.metric(source["id"], "unreadable_source_files", 1)
                if source["kind"] == "folder":
                    self.release_vanished(source, set(paths))
                for item in list(self.retired):
                    if item["source"] != source["id"]:
                        continue
                    try:
                        total += self.file(
                            source,
                            item["path"],
                            handle=item["handle"],
                            cursor_key=item["key"],
                        )
                    except Exception as exc:
                        if strict:
                            raise
                        failures.append((Path(item["path"]).name, str(exc)[:100]))
                    size = os.fstat(item["handle"].fileno()).st_size
                    if size != item["size"]:
                        item.update(size=size, quiet=time.monotonic())
                    if time.monotonic() - item["quiet"] > 300:
                        item["handle"].close()
                        self.retired.remove(item)
                        self.store.metric(source["id"], "rotation_watch_closed", 1)
                problems = []
                if failures:
                    problems.append(
                        f"{len(failures)} of {len(paths)} files could not be read ("
                        + "; ".join(f"{name}: {why}" for name, why in failures[:3])
                        + ")"
                    )
                if skipped:
                    problems.append(
                        f"{skipped} older matching files are not read: only the newest {MAX_FOLDER_FILES} are"
                    )
                if problems and not strict:
                    self.store.set_meta(
                        "health:" + source["id"],
                        dumps(
                            {
                                "status": "error",
                                "checked": time.time(),
                                "new_events": total,
                                "error": "; ".join(problems)[:300],
                            }
                        ),
                    )
                    return total
            if strict:
                return total
            self.store.set_meta(
                "health:" + source["id"],
                dumps({"status": "ok", "checked": time.time(), "new_events": total}),
            )
        except Exception as exc:
            if strict:
                raise
            self.store.set_meta(
                "health:" + source["id"],
                dumps(
                    {"status": "error", "checked": time.time(), "error": str(exc)[:300]}
                ),
            )
            # The interface shows the message; the log keeps where it came from.
            report("source " + str(source.get("name", source["id"])), exc)
        return total

    @staticmethod
    def newest_first(root, pattern):
        """Fresh files first, so a crowded folder never hides the newest logs."""

        def age(path):
            try:
                return -path.stat().st_mtime_ns
            except OSError:
                return 0

        return sorted(root.glob(pattern), key=lambda p: (age(p), str(p)))

    def retire(self, source, path, handle):
        """Keep draining a file that was rotated or removed, then let it go."""
        previous = os.fstat(handle.fileno())
        retired_key = (
            str(path) + "#rotated:" + str(previous.st_dev) + ":" + str(previous.st_ino)
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

    def release_vanished(self, source, present):
        """A deleted log left its handle open for good; hand it to the
        rotation watch, which closes it once the file stays quiet."""
        for key in [k for k in self.handles if k[0] == source["id"]]:
            path = Path(key[1])
            if path not in present and not path.exists():
                self.retire(source, path, self.handles.pop(key))

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
                self.retire(source, path, handle)
                del self.handles[key]
                handle = None
        if handle is None:
            if current is None:
                return 0
            if len(self.handles) + len(self.retired) >= 128:
                raise OSError(
                    "Open source/rotation handle limit reached; reduce sources or rotation frequency"
                )
            handle = open_source(path, self.store.directory)
            self.handles[key] = handle
        return self.file(source, path, handle=handle)

    def file(self, source, path, handle=None, cursor_key=None):
        if handle is None:
            with open_source(path, self.store.directory) as opened:
                return self.file(source, path, handle=opened, cursor_key=cursor_key)
        validate_source_handle(handle, self.store.directory)
        stat = os.fstat(handle.fileno())
        key = cursor_key or str(path)
        old = self.store.cursor(source["id"], key) or {}
        sig = [stat.st_dev, stat.st_ino]
        offset = 0
        # A cursor belongs to a file, not to the name it had when it was
        # written. After a rotation the same file turns up under a new name, and
        # the name it now has may already carry the cursor of the file that
        # used to be there: with numbered rotation, app.log.1 holds the cursor
        # of last cycle's app.log.1, and trusting it re-read the whole file
        # under a new generation, so every line counted again each cycle.
        if not old or old.get("identity") != sig:
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
            if not source.get("history") and not old.get("offset"):
                # An archive is past log. Without "import history" it is
                # recorded as seen, as a plain file's existing lines are; an
                # archive made by rotating a file already read would otherwise
                # be imported a second time. Enabling history later imports it.
                if not old.get("skipped"):
                    self.store.ingest(
                        source, [], key, {"stamp": stamp, "stable": True, "skipped": True}
                    )
                return 0
            # A new archive is imported only after an unchanged polling interval.
            if stat.st_size > MAX_ARCHIVE_BYTES:
                raise ValueError("Archive exceeds 64 MiB input limit")
            digest = old.get("digest") or file_digest(path, handle)
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
            def opener(*args):
                handle.seek(0)
                if path.suffix == ".gz":
                    return gzip.GzipFile(fileobj=handle, mode="rb")
                if path.suffix == ".xz":
                    return open_xz(handle)
                return bz2.BZ2File(handle, "rb")
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
        zone = machine_zone(self.store, source)
        try:
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
                    dropped = 0
                    if len(line) > MAX_LINE and not line.endswith(b"\n"):
                        # An event this long cannot be stored whole. Keep its
                        # beginning, where the cause of a failure usually is,
                        # and step over the rest so the cursor moves on. It used
                        # to raise here, which left the cursor in place: the
                        # source read the same line, failed, and stopped there
                        # for good.
                        ended = False
                        while True:
                            chunk = f.readline(MAX_LINE)
                            dropped += len(chunk)
                            if not chunk:
                                break
                            if chunk.endswith(b"\n"):
                                ended = True
                                break
                        if not ended and not compressed:
                            # Still being written: wait for its end like any line.
                            f.seek(begin)
                            break
                        dropped += len(line) - MAX_LINE
                        line = line[:MAX_LINE] + b"\n"
                    if compressed and begin + len(line) > MAX_EXPANDED_BYTES:
                        done = True
                        f.seek(begin)
                        break
                    if not line.endswith(b"\n") and not compressed:
                        f.seek(begin)
                        break
                    text = line.decode("utf-8", errors="replace").rstrip("\r\n")
                    if dropped:
                        text = fit_line(text, dropped)
                    if source.get("multiline") and text.startswith((" ", "\t")) and entries:
                        entries[-1]["message"] += "\n" + text
                        entries[-1]["raw"] += "\n" + text
                    elif text:
                        entries.append(normalize(text, key, f"{generation}:{begin}", zone))
                        if dropped:
                            entries[-1]["metadata"]["cut_bytes"] = dropped
                            self.store.metric(source["id"], "lines_cut", 1)
                    used += len(line) + dropped
                end = f.tell()
                tail = ""
                if not compressed:
                    f.seek(max(0, end - 64))
                    tail = hashlib.sha256(f.read(min(64, end))).hexdigest()
        except (EOFError, lzma.LZMAError, zlib.error, gzip.BadGzipFile) as exc:
            # A cut-off or damaged archive is a fact about that file, not a
            # crash: readers treat ValueError as "this source cannot be read".
            if isinstance(exc, lzma.LZMAError) and "emory" in str(exc):
                raise ValueError(
                    f"Compressed source needs more than {XZ_MEMORY_LIMIT >> 20} MiB of memory to read"
                ) from None
            raise ValueError(
                "Compressed source is truncated or corrupt: " + type(exc).__name__
            ) from None
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
        # Without --all, journalctl writes any field over 4096 bytes as null,
        # and a record whose MESSAGE is null used to be dropped without a trace.
        cmd = ["journalctl", "--no-pager", "--all", "-o", "json"]
        if cursor.get("cursor"):
            # Include the saved record to verify that retention did not erase it.
            cmd += ["--cursor", cursor["cursor"]]
        elif not source.get("history"):
            cmd += ["-n", "1"]
        # The inclusive cursor record is verification overhead, not new work.
        # Reserve a second bounded record so a large saved line cannot starve
        # the next record on every poll.
        budget = source['max_batch_bytes']
        raw, limited = read_journal(cmd, budget * (2 if cursor.get('cursor') else 1))
        collector = JournaldCollector(JournaldSourceConfig())
        entries = []
        last = None
        skipped = 0
        cursor_verified = not bool(cursor.get("cursor"))
        used = 0
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
            if not cursor_verified:
                if mark != cursor['cursor']:
                    raise ValueError("Journal cursor unavailable: possible retention gap; cursor preserved")
                cursor_verified = True
                continue
            if used + len(line) > budget:
                limited = True
                break
            used += len(line)
            last = mark
            e = collector._parse_json_line(text)
            if e:
                entries.append(
                    dict(e.model_dump(mode="json"), origin="journal:" + last)
                )
            elif data.get("MESSAGE") is None:
                skipped += 1
        if skipped:
            self.store.metric(source["id"], "journal_skipped", skipped)
        if limited and not last:
            raise ValueError("Journal record exceeds capture byte limit; cursor preserved")
        if last:
            if not cursor and not source.get("history"):
                entries = []
            return self.store.ingest(source, entries, "journal", {"cursor": last})
        return 0
