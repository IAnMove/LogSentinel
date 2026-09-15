"""Local limits and explicit operational errors, independent of model inference."""

import errno
import sqlite3
from pathlib import Path

import httpx
from pydantic import Field, model_validator

from .models import Model
from .journal_stream import JournalReadError


class SenderLimits(Model):
    max_pending_events: int = Field(default=100000, ge=100, le=10000000)
    min_free_mb: int = Field(default=256, ge=32, le=1000000)
    high_water_percent: int = Field(default=85, ge=20, le=95)
    resume_percent: int = Field(default=60, ge=10, le=90)
    io_pressure_percent: int = Field(default=25, ge=1, le=100)
    capture_batch_bytes: int = Field(default=262144, ge=4096, le=2000000)

    @model_validator(mode="after")
    def watermarks(self):
        if self.resume_percent >= self.high_water_percent:
            raise ValueError("resume_percent must be below high_water_percent")
        return self


class SenderWait(Exception):
    def __init__(self, code, seconds=30):
        self.code, self.seconds = code, seconds
        super().__init__(code)


def error_detail(exc):
    """Allowlisted diagnostics: never echo tokens, log content or response bodies."""
    if isinstance(exc, SenderWait):
        return dict(code=exc.code, retry_seconds=exc.seconds)
    if isinstance(exc, JournalReadError):
        return dict(code=exc.code, exit_status=exc.returncode)
    if isinstance(exc, TimeoutError):
        return dict(code="journal_read_timeout")
    if isinstance(exc, sqlite3.Error):
        code = getattr(exc, "sqlite_errorname", "SQLITE_ERROR")
        return dict(
            code=code if code.startswith("SQLITE_") else "SQLITE_ERROR",
            sqlite_code=getattr(exc, "sqlite_errorcode", None),
        )
    if isinstance(exc, httpx.HTTPStatusError):
        number = exc.response.status_code
        return dict(
            code={
                401: "authentication_failed",
                403: "forbidden",
                409: "receiver_paused",
                429: "receiver_quota",
                507: "receiver_storage_full",
            }.get(number, "http_error"),
            http_status=number,
        )
    if isinstance(exc, httpx.HTTPError):
        causes, current = [], exc
        for _ in range(8):
            if current is None:
                break
            causes.append(str(current).lower())
            current = current.__cause__ or current.__context__
        code = (
            "tls_failed"
            if any("certificate" in c or "ssl" in c for c in causes)
            else "connection_failed"
        )
        if isinstance(exc, httpx.TimeoutException):
            code = "network_timeout"
        return dict(code=code)
    if isinstance(exc, OSError):
        code = {
            errno.ENOSPC: "disk_full",
            errno.EIO: "storage_io_error",
            errno.EACCES: "permission_denied",
            errno.EROFS: "read_only_storage",
        }.get(exc.errno, "capture_io_error")
        if str(exc).startswith("Storage quota reached"):
            code = "queue_full"
        return dict(code=code, errno=exc.errno)
    if isinstance(exc, ValueError) and str(exc).startswith(
        "Journal cursor unavailable"
    ):
        return dict(code="journal_retention_gap")
    if isinstance(exc, ValueError) and str(exc).startswith("Journal record exceeds"):
        return dict(code="journal_record_too_large")
    return dict(code=type(exc).__name__)


def io_pressure():
    """Linux full I/O stall pressure; unavailable PSI is reported as unknown."""
    try:
        for line in Path("/proc/pressure/io").read_text().splitlines():
            if line.startswith("full "):
                return float(
                    dict(part.split("=") for part in line.split()[1:])["avg10"]
                )
    except (OSError, ValueError, KeyError):
        pass
    return None


class CaptureGate:
    def __init__(self, store, limits):
        self.store, self.limits = store, limits
        self.congested = False
        self.io_congested = False
        self.last_snapshot = {}

    def check(self, *, delivery=False):
        pressure = io_pressure()
        threshold = (
            self.limits.io_pressure_percent / 2
            if self.io_congested
            else self.limits.io_pressure_percent
        )
        self.io_congested = pressure is not None and pressure >= threshold
        if self.io_congested:
            raise SenderWait("disk_io_pressure")
        usage = self.store.storage_usage()
        self.last_snapshot = dict(usage, io_pressure_percent=pressure)
        minimum = (16 if delivery else self.limits.min_free_mb) * 1024**2
        if usage["disk_free_bytes"] < minimum:
            raise SenderWait("disk_free_reserve")
        if delivery:
            return
        pending = self.store.sender_pending()
        ratio = (
            self.limits.resume_percent / 100
            if self.congested
            else self.limits.high_water_percent / 100
        )
        maximum = self.limits.max_pending_events * (
            self.limits.resume_percent / 100 if self.congested else 1
        )
        self.congested = (
            usage["used_bytes"] >= usage["quota_bytes"] * ratio or pending >= maximum
        )
        if self.congested:
            raise SenderWait("queue_high_water")
