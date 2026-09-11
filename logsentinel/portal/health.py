"""Deterministic observer health and recoveries, independent of LLM inference."""

from datetime import datetime, timezone
import json
import shutil
import time
import threading

from .models import Source
from .rules import sanitize
from .store import dumps, uid


class HealthMonitor:
    def __init__(self, store, analyzer, monitor, telemetry, background=True):
        self.store, self.analyzer = store, analyzer
        self.monitor, self.telemetry = monitor, telemetry
        self.background = background
        self.started = time.time()
        self.lock = threading.RLock()
        self.beats = {}
        self.last_tick = None
        self.snapshot = {"checked": None, "checks": [], "state": "starting"}

    def beat(self, worker):
        self.beats[worker] = time.time()

    def conditions(self):
        now = time.time()
        cfg = self.store.settings()
        machines = [
            m
            for m in self.store.objects("machine")
            if self.store.monitoring_active(m["id"])
        ]
        local = next((m["id"] for m in machines if m["kind"] == "local"), "")
        checks = []

        def add(
            key,
            machine,
            bad,
            title,
            detail,
            severity="HIGH",
            enabled=True,
            liveness=True,
            alert=True,
        ):
            checks.append(
                dict(
                    key=key,
                    machine_id=machine,
                    bad=bool(bad),
                    title=title,
                    detail=detail,
                    severity=severity,
                    enabled=enabled,
                    liveness=liveness,
                    alert=alert,
                )
            )

        for machine in machines:
            id = machine["id"]
            metrics = self.telemetry.data.config(id)
            if metrics.enabled:
                latest = self.telemetry.data.latest(id)
                last = latest["observed"] if latest else None
                key = "metrics:" + id
                since = float(self.store.meta("health_since:" + key) or now)
                self.store.set_meta("health_since:" + key, str(since))
                limit = metrics.interval_seconds * metrics.stale_intervals
                add(
                    key,
                    id,
                    now - max(last or since, since) > limit,
                    "Machine measurements stopped",
                    dict(
                        last_sample=last,
                        timeout_seconds=limit,
                        mode=metrics.mode,
                        meaning="No fresh measurements; this does not prove the machine itself is down",
                    ),
                )
            else:
                self.store.set_meta("health_since:metrics:" + id, str(now))
        for source in self.store.objects("source"):
            if not source["enabled"] or not self.store.monitoring_active(
                source["machine_id"]
            ):
                self.store.set_meta("health_since:source:" + source["id"], str(now))
                continue
            if source["kind"] in ("metrics", "health"):
                continue
            health = json.loads(self.store.meta("health:" + source["id"]) or "{}")
            remote = source["kind"] == "push"
            timeout = source.get("heartbeat_timeout_seconds", 0) if remote else 60
            if remote and not timeout:
                continue  # A quiet log is not evidence of a broken sender.
            last = health.get("heartbeat", health.get("checked"))
            since = float(self.store.meta("health_since:source:" + source["id"]) or now)
            self.store.set_meta("health_since:source:" + source["id"], str(since))
            stale = now - max(last or since, since) > timeout
            add(
                "source:" + source["id"],
                source["machine_id"],
                health.get("status") == "error" or stale,
                "Log source needs attention",
                dict(
                    source_id=source["id"],
                    source_name=source["name"],
                    last_check=last,
                    timeout_seconds=timeout,
                    receiver_health=health,
                    meaning="Checks or sender heartbeats, not log volume, determine availability",
                ),
            )
        quota = cfg.disk_limit_mb * 1024**2
        size = self.store.size()
        disk = shutil.disk_usage(self.store.directory)
        add(
            "storage",
            local,
            size / quota * 100 >= cfg.storage_warning_percent
            or disk.free < 128 * 1024**2,
            "Observer storage is approaching capacity",
            dict(
                database_bytes=size,
                quota_bytes=quota,
                quota_percent=round(size / quota * 100, 2),
                disk_free_bytes=disk.free,
                warning_percent=cfg.storage_warning_percent,
            ),
            "CRITICAL" if size >= quota or disk.free < 32 * 1024**2 else "HIGH",
        )
        for worker, meta in (
            ("capture", "collector_error"),
            ("metrics", "telemetry_worker_error"),
            ("analysis", "worker_error"),
            ("notifications", "delivery_worker_error"),
        ):
            error = self.store.meta(meta) or ""
            last = self.beats.get(worker, self.started)
            stale = self.background and worker != "analysis" and now - last > 60
            add(
                "worker:" + worker,
                local,
                bool(error) or stale,
                "Observer worker needs attention",
                dict(worker=worker, error=error, last_heartbeat=last),
            )
        usage = self.store.rows("usage", 3)
        failed = (
            len(usage) == 3
            and all(u["status"] == "error" for u in usage)
            and usage[0]["created"] > now - 3600
        )
        add(
            "model",
            local,
            failed,
            "Recent model requests failed",
            dict(
                recent_results=[
                    dict(kind=u["kind"], status=u["status"], created=u["created"])
                    for u in usage
                ],
                meaning="Failures may be connectivity or response-format errors; inspect Activity",
            ),
        )
        from .capacity import recent_coverage

        signal = recent_coverage(self.store)
        add(
            "coverage",
            local,
            signal["level"] != "ok",
            "Log review is behind incoming volume",
            dict(
                signal,
                meaning="Unreviewed events are not a clean security result. Capture can still be healthy.",
            ),
            "CRITICAL" if signal["level"] == "critical" else "MEDIUM",
            liveness=False,
            alert=False,
        )
        return checks

    def report(self, check, recovered=False, notify=True):
        machine = check["machine_id"]
        if not machine:
            return None  # Global diagnostics remain visible without inventing a machine identity.
        source_id = "health:" + machine
        source = self.store.get("source", source_id)
        if not source:
            self.store.put(
                "source",
                Source(
                    name="Observer health",
                    machine_id=machine,
                    kind="health",
                    enabled=True,
                ).model_dump(),
                source_id,
            )
            source = self.store.get("source", source_id)
        detail = sanitize(check["detail"], (self.store.settings().llm.api_key,))
        origin = "health:" + uid()
        message = "Observer condition: " + check["key"]
        now = time.time()
        metadata = dict(
            check=check["key"], recovered=recovered, observed=now, measurement=detail
        )
        self.store.ingest(
            source,
            [
                dict(
                    origin=origin,
                    service="observer-health",
                    message=message,
                    raw=message + " " + dumps(metadata),
                    timestamp=datetime.fromtimestamp(now, timezone.utc).isoformat(),
                    metadata=metadata,
                )
            ],
        )
        with self.store.connect() as db:
            event = db.execute(
                "SELECT id FROM events WHERE source_id=? AND origin=?",
                (source_id, origin),
            ).fetchone()[0]
        self.store.mark([event], "measured")
        es = self.store.settings().language == "es"
        label = (
            {
                "Machine measurements stopped": "Se han detenido las mediciones de una máquina",
                "Log source needs attention": "Una fuente de logs necesita atención",
                "Observer storage is approaching capacity": "El almacenamiento del observador se acerca al límite",
                "Observer worker needs attention": "Un proceso del observador necesita atención",
                "Recent model requests failed": "Han fallado las últimas consultas al modelo",
                "Log review is behind incoming volume": "La revisión de logs va por detrás del volumen recibido",
            }.get(check["title"], check["title"])
            if es
            else check["title"]
        )
        finding = dict(
            title=(("Recuperado: " if es else "Recovered: ") if recovered else "")
            + label,
            summary=(
                "Comprobación automática recuperada. "
                if recovered and es
                else "Automatic check recovered. " if recovered else ""
            )
            + dumps(detail),
            severity=check["severity"],
            category="monitor.health",
            evidence_ids=[event],
            reasoning="Observed by a deterministic check; this is not an LLM diagnosis.",
            next_steps="Inspect Health, source status, storage, Activity and sender service logs. A stopped observer requires independent external supervision.",
        )
        return self.analyzer.save_finding(
            machine,
            finding,
            [event],
            status="resolved" if recovered else "open",
            notify=notify,
        )

    def tick(self):
        with self.lock:
            return self._tick()

    def _tick(self):
        now = time.time()
        cfg = self.store.settings()
        checks = self.conditions()
        seen = set()
        for check in checks:
            key = "health_condition:" + check["key"]
            seen.add(key)
            state = json.loads(self.store.meta(key) or "{}")
            bad_since = state.get("bad_since") if check["bad"] else None
            if check["bad"] and bad_since is None:
                bad_since = now
            active = bool(check["bad"] and now - bad_since >= cfg.health_grace_seconds)
            try:
                if (
                    cfg.health_alerts
                    and check.get("alert", True)
                    and active
                    and (
                        not state.get("active")
                        or not state.get("problem_id")
                        or check["severity"] == "CRITICAL"
                        and state.get("severity") != "CRITICAL"
                    )
                ):
                    state["problem_id"] = self.report(check)
                if not check["bad"] and state.get("active") and state.get("problem_id"):
                    check["severity"] = state.get("severity", check["severity"])
                    self.report(check, recovered=True, notify=cfg.health_alerts)
            except OSError:
                check["persistence_error"] = (
                    "Storage full; condition remains visible but evidence could not be saved"
                )
                active = state.get("active", False)
            state.update(
                active=active,
                bad_since=bad_since,
                checked=now,
                severity=check["severity"],
                check=check,
            )
            self.store.set_meta(key, dumps(state))
            check.update(
                active=active, problem_id=state.get("problem_id"), bad_since=bad_since
            )
        # Disabling monitoring is not evidence of recovery; retain the open incident.
        with self.store.connect() as db:
            for row in db.execute(
                "SELECT key,value FROM meta WHERE key LIKE 'health_condition:%'"
            ).fetchall():
                if row["key"] not in seen:
                    state = json.loads(row["value"])
                    state.update(active=False, bad_since=None, disabled=True)
                    db.execute(
                        "UPDATE meta SET value=? WHERE key=?",
                        (dumps(state), row["key"]),
                    )
        self.last_tick = now
        self.snapshot = dict(
            checked=now,
            state=(
                "degraded"
                if any(c["bad"] and c.get("liveness", True) for c in checks)
                else "ok"
            ),
            checks=checks,
        )
        return self.snapshot

    def state(self):
        stale = self.background and time.time() - (self.last_tick or self.started) > 60
        return dict(
            self.snapshot,
            state="stale" if stale else self.snapshot["state"],
            supervision_enabled=self.store.settings().health_alerts,
            background=self.background,
        )
