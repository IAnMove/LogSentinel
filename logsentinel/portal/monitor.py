"""Shared, observable scheduler state. Collection and inference are independent."""

import json
import time


class Monitor:
    def __init__(self, store, analyzer, background):
        self.store, self.analyzer = store, analyzer
        self.background = background
        self.next_due = time.time()
        self.capture_heartbeat = None
        self.signature = None

    def reschedule(self):
        cfg = self.store.settings()
        signature = (cfg.enabled, cfg.interval_seconds)
        if signature != self.signature:
            self.next_due = time.time()
            self.signature = signature

    async def tick(self):
        self.reschedule()
        cfg = self.store.settings()
        # Manual scans also reset the interval. Diagnostic/chat calls don't.
        if self.analyzer.started:
            self.next_due = max(
                self.next_due, self.analyzer.started + cfg.interval_seconds
            )
        if (
            cfg.enabled
            and time.time() >= self.next_due
            and not self.analyzer.lock.locked()
        ):
            self.next_due = time.time() + cfg.interval_seconds
            await self.analyzer.cycle()

    def state(self):
        self.reschedule()
        cfg = self.store.settings()
        sources = [
            s
            for s in self.store.objects("source")
            if s["enabled"] and s["kind"] != "metrics"
        ]
        result = json.loads(self.store.meta("analysis_result") or "{}")
        health = {
            s["id"]: json.loads(self.store.meta("health:" + s["id"]) or "{}")
            for s in sources
        }
        with self.store.connect() as db:
            counts = dict(
                db.execute("SELECT status,count(*) FROM events GROUP BY status")
            )
            failed = db.execute(
                "SELECT count(*) FROM jobs WHERE status IN ('failed','retry')"
            ).fetchone()[0]
            last_event = db.execute("SELECT max(received) FROM events").fetchone()[0]
        due = max(self.next_due, (self.analyzer.started or 0) + cfg.interval_seconds)
        capture = "inactive"
        if self.background and sources:
            capture = (
                "starting"
                if self.capture_heartbeat is None
                else (
                    "active" if time.time() - self.capture_heartbeat < 30 else "delayed"
                )
            )
        return {
            "server_time": time.time(),
            "background": self.background,
            "capture": capture,
            "capture_heartbeat": self.capture_heartbeat,
            "last_event": last_event,
            "enabled_sources": len(sources),
            "source_health": health,
            "collector_error": self.store.meta("collector_error"),
            "worker_error": self.store.meta("worker_error"),
            "analysis_enabled": cfg.enabled,
            "analysis_running": self.analyzer.running,
            "model_busy": self.analyzer.lock.locked(),
            "interval_seconds": cfg.interval_seconds,
            "next_analysis": due if cfg.enabled and self.background else None,
            "last_started": self.analyzer.started or result.get("started"),
            "last_finished": self.analyzer.finished or result.get("finished"),
            "last_outcome": self.analyzer.outcome or result.get("outcome"),
            "pending": counts.get("pending", 0),
            "capacity": counts.get("capacity", 0),
            "error_events": counts.get("error", 0),
            "failed_jobs": failed,
        }
