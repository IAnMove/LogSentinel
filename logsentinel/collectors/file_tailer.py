"""File tailing collector for standard Linux log files."""

from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
import os
import logging
from pathlib import Path
import re
from typing import AsyncGenerator, Dict, List, Optional
from logsentinel.config import FileSourceConfig
from logsentinel.core.models import LogEntry, LogSourceType
from logsentinel.collectors.base import BaseCollector


MAX_LINE_BYTES = 256_000


class FileTailerCollector(BaseCollector):
    """Tails one or more log files and yields LogEntry objects."""

    def __init__(self, config: FileSourceConfig):
        self.config = config
        self._running = False
        self._file_positions: Dict[str, int] = {}
        self._file_inodes: Dict[str, int] = {}

    def get_existing_paths(self) -> List[Path]:
        """Filter paths that actually exist and are readable."""
        existing = []
        for p_str in self.config.paths:
            p = Path(p_str).expanduser().resolve()
            if p.is_file() and os.access(p, os.R_OK):
                existing.append(p)
        return existing

    async def stream(self) -> AsyncGenerator[LogEntry, None]:
        if not self.config.enabled:
            return

        self._running = True
        handles = {}
        paths = [Path(p).expanduser().absolute() for p in self.config.paths]

        def complete_lines(handle, path):
            # Byte offsets stay valid even when UTF-8 characters span writes.
            while True:
                position = handle.tell()
                # One runaway line must not become one runaway allocation.
                line = handle.readline(MAX_LINE_BYTES + 1)
                if len(line) > MAX_LINE_BYTES and not line.endswith(b"\n"):
                    while True:  # keep the head as the event and drop the rest of the line
                        rest = handle.readline(MAX_LINE_BYTES)
                        if not rest or rest.endswith(b"\n"):
                            break
                    line = line[:MAX_LINE_BYTES] + b"\n"
                if not line.endswith(b"\n"):
                    handle.seek(position)
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    yield self.parse_log_line(text, source_path=str(path))

        try:
            # Only files present at startup skip history. New files start at 0.
            for path in paths:
                try:
                    handle = path.open("rb")
                    handle.seek(0, os.SEEK_END)
                    handles[path] = handle
                except FileNotFoundError:
                    pass
                except OSError as exc:
                    logging.getLogger(__name__).warning("Cannot tail %s: %s", path, exc)

            while self._running:
                for path in paths:
                    try:
                        handle = handles.get(path)
                        try:
                            current = path.stat()
                        except FileNotFoundError:
                            current = None
                        if handle:
                            previous = os.fstat(handle.fileno())
                            if previous.st_size < handle.tell():
                                handle.seek(0)
                            yield_from = complete_lines(handle, path)
                            for entry in yield_from:
                                yield entry
                            if current and (previous.st_dev, previous.st_ino) != (current.st_dev, current.st_ino):
                                # Drain the old descriptor before switching paths.
                                handle.close()
                                handles.pop(path)
                                handle = None
                        if handle is None and current is not None:
                            handle = path.open("rb")
                            handles[path] = handle
                            for entry in complete_lines(handle, path):
                                yield entry
                    except OSError as exc:
                        logging.getLogger(__name__).warning("Cannot tail %s: %s", path, exc)
                await asyncio.sleep(self.config.poll_interval_seconds)
        finally:
            for handle in handles.values():
                handle.close()

    async def stop(self) -> None:
        self._running = False

    @staticmethod
    def parse_log_line(raw_line: str, source_path: str = "file", tz=None) -> LogEntry:
        """Parse standard Linux syslog or raw log line into LogEntry.

        tz is the zone of the machine that wrote the line; it applies to
        timestamps that carry none. Without it they are read as UTC.
        """
        zone = tz or timezone.utc
        now = datetime.now(timezone.utc)
        ts = now
        inferred = True
        payload = raw_line
        prefix = re.match(
            r"^(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\s+(.*)$",
            raw_line,
        )
        legacy = re.match(r"^([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})\s+(.*)$", raw_line)
        if prefix:
            stamp, payload = prefix.groups()
            try:
                parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
                inferred = parsed.tzinfo is None
                ts = (parsed.replace(tzinfo=zone) if inferred else parsed).astimezone(timezone.utc)
            except ValueError:
                pass
        elif legacy:
            stamp, payload = legacy.groups()
            # RFC3164 has neither year nor timezone: useful display time, never
            # trustworthy behavioral evidence. A log line is written in the
            # past, so take the most recent year that does not put it in the
            # future (allowing a day of clock skew). The nearest year put
            # "Feb 10" seen in September into the following February.
            local_year = now.astimezone(zone).year
            candidates = []
            for year in range(local_year, local_year - 5, -1):
                try:
                    candidates.append(datetime.strptime(f"{year} {stamp}", "%Y %b %d %H:%M:%S").replace(tzinfo=zone))
                except ValueError:
                    pass  # e.g. Feb 29 in a common year
            plausible = [c for c in candidates if c <= now + timedelta(days=1)]
            if plausible:
                ts = max(plausible).astimezone(timezone.utc)
            elif candidates:
                ts = min(candidates).astimezone(timezone.utc)

        match = re.match(r"^([\w.\-]+)\s+([\w.\-/]+?)(?:\[(\d+)\])?:\s*(.*)$", payload) if prefix or legacy else None
        host, service, pid, message = None, Path(source_path).stem, None, raw_line
        if match:
            host, service, pid_str, message = match.groups()
            pid = int(pid_str) if pid_str else None
        return LogEntry(
            source_type=LogSourceType.FILE,
            source_name=source_path,
            service=service,
            message=message,
            raw=raw_line,
            pid=pid,
            hostname=host,
            timestamp=ts,
            metadata={"timestamp_inferred": inferred},
        )
