"""Read-only Linux host sampling and compressed, idempotent time-series storage."""

from datetime import datetime, timezone
import gzip
import json
import os
from pathlib import Path
import re
import time
from typing import Literal

from pydantic import Field, field_validator, model_validator
from .models import Model
from .store import dumps, uid


class TelemetryConfig(Model):
    enabled: bool = False
    mode: Literal["local", "remote"] = "remote"
    interval_seconds: int = Field(default=60, ge=10, le=3600)
    disk_paths: list[str] = Field(
        default_factory=lambda: ["/"], min_length=1, max_length=16
    )
    retention_days: int = Field(default=30, ge=1, le=365)
    daily_retention_days: int = Field(default=365, ge=30, le=3650)
    cpu_threshold: float = Field(default=90, ge=10, le=100)
    ram_threshold: float = Field(default=90, ge=10, le=100)
    swap_threshold: float = Field(default=80, ge=10, le=100)
    disk_threshold: float = Field(default=90, ge=10, le=100)
    inode_threshold: float = Field(default=90, ge=10, le=100)
    consecutive_samples: int = Field(default=3, ge=1, le=30)
    critical_threshold: float = Field(default=98, ge=10, le=100)
    cpu_critical_samples: int = Field(default=3, ge=1, le=30)
    notify_recovery: bool = True
    stale_intervals: int = Field(default=3, ge=2, le=60)
    spike_points: float = Field(default=30, ge=5, le=100)
    cooldown_seconds: int = Field(default=1800, ge=60, le=86400)
    llm_enabled: bool = False
    llm_interval_seconds: int = Field(default=3600, ge=900, le=86400)

    @model_validator(mode="after")
    def retention_order(self):
        if self.daily_retention_days < self.retention_days:
            raise ValueError(
                "Daily summaries must be retained at least as long as samples"
            )
        return self

    @field_validator("disk_paths")
    @classmethod
    def absolute_paths(cls, paths):
        if any(
            not p.startswith("/") or len(p) > 1024 or "\n" in p or "\x00" in p
            for p in paths
        ):
            raise ValueError("Use absolute disk paths, one per line")
        return list(dict.fromkeys(paths))


KEYS = {
    "cpu_pct",
    "iowait_pct",
    "ram_pct",
    "ram_total_bytes",
    "ram_available_bytes",
    "swap_pct",
    "swap_total_bytes",
    "swap_used_bytes",
    "load1",
    "load5",
    "load15",
    "cpu_count",
    "uptime_seconds",
}


class MetricSample(Model):
    id: str = Field(default_factory=uid, min_length=1, max_length=100)
    observed: float = Field(default_factory=time.time, ge=0)
    values: dict[str, float] = Field(min_length=1, max_length=100)
    errors: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("values")
    @classmethod
    def valid_values(cls, values):
        for key, value in values.items():
            if key not in KEYS and not re.fullmatch(
                r"(?:disk_pct|inode_pct|disk_total_bytes|disk_available_bytes):/[^\x00\n]{0,1023}",
                key,
            ):
                raise ValueError("Unknown metric: " + key[:100])
            if not 0 <= value <= 1e20 or (
                key.split(":", 1)[0].endswith("_pct") and value > 100
            ):
                raise ValueError("Invalid metric value")
        return values

    @field_validator("errors")
    @classmethod
    def bounded_errors(cls, values):
        if any(len(v) > 200 for v in values):
            raise ValueError("Metric error exceeds 200 characters")
        return values


class LinuxSampler:
    """CPU needs two reads; MemAvailable excludes reclaimable cache pressure.

    See https://docs.kernel.org/filesystems/proc.html. No process arguments,
    environment variables, root privileges or changes to host settings.
    """

    def __init__(self, proc="/proc"):
        self.proc = Path(proc)
        self.previous_cpu = None

    def sample(self, paths):
        values, errors = {}, []
        try:
            stat = (self.proc / "stat").read_text().splitlines()
            parts = [int(v) for v in stat[0].split()[1:9]]
            total, idle, wait = sum(parts), parts[3], parts[4]
            if self.previous_cpu:
                old_total, old_idle, old_wait = self.previous_cpu
                elapsed = total - old_total
                if elapsed > 0 and idle >= old_idle and wait >= old_wait:
                    values["cpu_pct"] = max(
                        0,
                        min(
                            100,
                            100
                            * (elapsed - (idle - old_idle) - (wait - old_wait))
                            / elapsed,
                        ),
                    )
                    values["iowait_pct"] = max(
                        0, min(100, 100 * (wait - old_wait) / elapsed)
                    )
            self.previous_cpu = (total, idle, wait)
            values["cpu_count"] = (
                sum(bool(re.match(r"cpu\d+ ", line)) for line in stat)
                or os.cpu_count()
                or 1
            )
        except (OSError, ValueError, IndexError):
            errors.append("CPU counters unavailable")
        try:
            mem = {
                line.split(":")[0]: int(line.split()[1]) * 1024
                for line in (self.proc / "meminfo").read_text().splitlines()
            }
            total, available = mem["MemTotal"], mem["MemAvailable"]
            values.update(
                ram_total_bytes=total,
                ram_available_bytes=available,
                ram_pct=100 * max(0, total - available) / total,
            )
            total, free = mem["SwapTotal"], mem["SwapFree"]
            values.update(swap_total_bytes=total, swap_used_bytes=max(0, total - free))
            if total:
                values["swap_pct"] = 100 * max(0, total - free) / total
        except (OSError, ValueError, KeyError, IndexError, ZeroDivisionError):
            errors.append("Memory counters unavailable")
        try:
            load = (self.proc / "loadavg").read_text().split()
            values.update(zip(("load1", "load5", "load15"), map(float, load[:3])))
            values["uptime_seconds"] = float(
                (self.proc / "uptime").read_text().split()[0]
            )
        except (OSError, ValueError, IndexError):
            errors.append("Load or uptime unavailable")
        for path in paths:
            try:
                stat = os.statvfs(path)
                total = stat.f_blocks * stat.f_frsize
                available = max(0, stat.f_bavail) * stat.f_frsize
                values["disk_total_bytes:" + path] = total
                values["disk_available_bytes:" + path] = available
                if total:
                    # Includes reserved space unavailable to the service user.
                    values["disk_pct:" + path] = 100 * max(0, total - available) / total
                if stat.f_files:
                    values["inode_pct:" + path] = (
                        100 * max(0, stat.f_files - stat.f_favail) / stat.f_files
                    )
            except OSError:
                errors.append(("Disk unavailable: " + path)[:200])
        return MetricSample(values=values, errors=errors)


class TelemetryStore:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS telemetry_samples(machine_id TEXT,id TEXT,observed REAL,received REAL,data BLOB,evaluated INTEGER DEFAULT 0,PRIMARY KEY(machine_id,id));
                CREATE INDEX IF NOT EXISTS telemetry_time ON telemetry_samples(machine_id,observed);
                CREATE TABLE IF NOT EXISTS telemetry_rollups(machine_id TEXT,period TEXT,bucket TEXT,key TEXT,n INTEGER,total REAL,minimum REAL,maximum REAL,PRIMARY KEY(machine_id,period,bucket,key));
                CREATE TABLE IF NOT EXISTS telemetry_alerts(machine_id TEXT,key TEXT,data TEXT,PRIMARY KEY(machine_id,key));
            """
            )

    def config(self, machine):
        data = self.store.get("telemetry_config", "telemetry:" + machine) or {}
        return TelemetryConfig.model_validate(
            {k: v for k, v in data.items() if k != "id"}
        )

    def latest(self, machine):
        with self.store.connect() as db:
            row = db.execute(
                "SELECT data,received FROM telemetry_samples WHERE machine_id=? ORDER BY observed DESC LIMIT 1",
                (machine,),
            ).fetchone()
        return (
            dict(json.loads(gzip.decompress(row[0])), received=row[1]) if row else None
        )

    def save(self, machine, sample):
        cfg = self.config(machine)
        now = time.time()
        if not now - cfg.retention_days * 86400 <= sample.observed <= now + 60:
            raise ValueError(
                "Metric timestamp is outside retention or more than 60 seconds in the future"
            )
        raw = dumps(sample.model_dump()).encode()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT data FROM telemetry_samples WHERE machine_id=? AND id=?",
                (machine, sample.id),
            ).fetchone()
            if old:
                if json.loads(gzip.decompress(old[0])) != sample.model_dump():
                    raise ValueError(
                        "Sample ID was already used for different measurements"
                    )
                return False
            if (
                self.store.size() + len(raw) * 4 + 32768
                > self.store.settings().disk_limit_mb * 1024**2
            ):
                raise OSError("Storage quota reached")
            db.execute(
                "INSERT INTO telemetry_samples VALUES(?,?,?,?,?,0)",
                (machine, sample.id, sample.observed, now, gzip.compress(raw, mtime=0)),
            )
            self.store._metric(db, "metrics:" + machine, "metric_samples_received", 1)
            self.store._metric(
                db, "metrics:" + machine, "metric_logical_bytes", len(raw)
            )
            stamp = datetime.fromtimestamp(sample.observed, timezone.utc)
            for period, bucket in (
                ("hour", stamp.strftime("%Y-%m-%dT%H:00:00Z")),
                ("day", stamp.strftime("%Y-%m-%d")),
            ):
                for key, value in sample.values.items():
                    db.execute(
                        "INSERT INTO telemetry_rollups VALUES(?,?,?,?,1,?,?,?) ON CONFLICT(machine_id,period,bucket,key) DO UPDATE SET n=n+1,total=total+excluded.total,minimum=min(minimum,excluded.minimum),maximum=max(maximum,excluded.maximum)",
                        (machine, period, bucket, key, value, value, value),
                    )
        return True

    def rollups(self, machine, period="hour", days=1):
        fmt = "%Y-%m-%d" if period == "day" else "%Y-%m-%dT%H:00:00Z"
        since = datetime.fromtimestamp(
            time.time() - days * 86400, timezone.utc
        ).strftime(fmt)
        with self.store.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT bucket,key,n,minimum,maximum,total/n average FROM telemetry_rollups WHERE machine_id=? AND period=? AND bucket>=? ORDER BY bucket,key",
                    (machine, period, since),
                )
            ]

    def baseline(self, machine, observed):
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT data FROM telemetry_samples WHERE machine_id=? AND observed<? AND observed>=? ORDER BY observed DESC LIMIT 10",
                (
                    machine,
                    observed,
                    observed - self.config(machine).interval_seconds * 15,
                ),
            ).fetchall()
        return [json.loads(gzip.decompress(r[0])) for r in rows]

    def prune(self):
        removed = 0
        with self.store.connect() as db:
            for machine in self.store.objects("machine"):
                cfg = self.config(machine["id"])
                cutoff = time.time() - cfg.retention_days * 86400
                removed += db.execute(
                    "DELETE FROM telemetry_samples WHERE machine_id=? AND observed<?",
                    (machine["id"], cutoff),
                ).rowcount
                db.execute(
                    "DELETE FROM telemetry_rollups WHERE machine_id=? AND period='hour' AND bucket<?",
                    (
                        machine["id"],
                        datetime.fromtimestamp(cutoff, timezone.utc).isoformat()[:13],
                    ),
                )
                db.execute(
                    "DELETE FROM telemetry_rollups WHERE machine_id=? AND period='day' AND bucket<?",
                    (
                        machine["id"],
                        datetime.fromtimestamp(
                            time.time() - cfg.daily_retention_days * 86400, timezone.utc
                        ).strftime("%Y-%m-%d"),
                    ),
                )
        if removed:
            with self.store.connect() as db:
                db.execute("VACUUM")
        return removed
