"""Systemd journal log collector using journalctl."""

from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
import json
import shutil
from typing import AsyncGenerator, List, Optional
from logsentinel.config import JournaldSourceConfig
from logsentinel.core.models import LogEntry, LogSourceType
from logsentinel.collectors.base import BaseCollector


class JournaldCollector(BaseCollector):
    """Streams logs from systemd journal via journalctl -f -o json."""

    def __init__(self, config: JournaldSourceConfig):
        self.config = config
        self.journalctl_bin = shutil.which("journalctl")
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._running = False

    def is_available(self) -> bool:
        """Check if journalctl command is available."""
        return self.journalctl_bin is not None

    def _build_command(self, follow: bool = True, lines: Optional[int] = None) -> List[str]:
        if not self.journalctl_bin:
            raise RuntimeError("journalctl binary not found on this system.")

        cmd = [self.journalctl_bin, "-o", "json"]
        if follow:
            cmd.append("-f")
        if lines is not None:
            cmd.extend(["-n", str(lines)])
        if self.config.priority:
            cmd.extend(["-p", self.config.priority])
        for unit in self.config.units:
            cmd.extend(["-u", unit])
        cmd.extend(self.config.extra_args)
        return cmd

    async def stream(self) -> AsyncGenerator[LogEntry, None]:
        """Continuously stream new journal entries."""
        if not self.is_available() or not self.config.enabled:
            return

        self._running = True
        cmd = self._build_command(follow=True, lines=0)

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )

            assert self._proc.stdout is not None
            while self._running:
                line = await self._proc.stdout.readline()
                if not line:
                    code = await self._proc.wait()
                    if self._running and code != 0:
                        raise RuntimeError(f"journalctl exited with status {code}")
                    break
                entry = self._parse_json_line(line.decode("utf-8", errors="replace").strip())
                if entry:
                    yield entry
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    async def read_recent(self, lines: int = 100) -> List[LogEntry]:
        """Read the most recent journal entries in batch."""
        if not self.is_available():
            raise RuntimeError("journalctl binary not found on this system.")

        cmd = self._build_command(follow=False, lines=lines)
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"journalctl exited with status {proc.returncode}")
        entries = []
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            entry = self._parse_json_line(line)
            if entry:
                entries.append(entry)
        return entries

    async def stop(self) -> None:
        """Terminate the journalctl process."""
        self._running = False
        if self._proc:
            try:
                self._proc.terminate()
                await asyncio.wait_for(self._proc.wait(), timeout=2.0)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def _parse_json_line(self, line: str) -> Optional[LogEntry]:
        if not line.startswith("{"):
            return None
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None

        # Extract message: might be string or byte array
        msg_val = data.get("MESSAGE", "")
        if isinstance(msg_val, list):
            # Byte array
            if not all(type(v) is int and 0 <= v <= 255 for v in msg_val):
                return None
            message = bytes(msg_val).decode("utf-8", errors="replace")
        elif isinstance(msg_val, str):
            message = msg_val
        else:
            return None

        if not message.strip():
            return None

        # Extract service
        service = next((data[key] for key in ("SYSLOG_IDENTIFIER", "_SYSTEMD_UNIT", "_COMM")
                        if isinstance(data.get(key), str) and data[key]), "kernel")
        # Strip trailing .service if present
        if service.endswith(".service"):
            service = service[:-8]

        # Extract priority
        priority = None
        if "PRIORITY" in data:
            try:
                priority = int(data["PRIORITY"])
            except (ValueError, TypeError, OverflowError):
                pass

        # Extract timestamp
        ts = datetime.now(timezone.utc)
        inferred = True
        if "__REALTIME_TIMESTAMP" in data:
            try:
                # journalctl uses microseconds
                micros = int(data["__REALTIME_TIMESTAMP"])
                ts = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=micros)
                inferred = False
            except Exception:
                pass

        pid = None
        if "_PID" in data:
            try:
                pid = int(data["_PID"])
            except (ValueError, TypeError, OverflowError):
                pass

        hostname = data.get("_HOSTNAME")
        if not isinstance(hostname, str):
            hostname = None

        return LogEntry(
            source_type=LogSourceType.JOURNALD,
            source_name="journald",
            service=service,
            message=message,
            raw=line,
            priority=priority,
            pid=pid,
            hostname=hostname,
            timestamp=ts,
            metadata={
                "timestamp_inferred": inferred,
                "systemd_unit": data.get("_SYSTEMD_UNIT"),
                "systemd_user_unit": data.get("_SYSTEMD_USER_UNIT"),
                "transport": data.get("_TRANSPORT"),
                "exe": data.get("_EXE"),
                "cmdline": data.get("_CMDLINE"),
            },
        )
