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
        signature = (cfg.enabled, cfg.interval_seconds, cfg.adaptive_batching)
        if signature != self.signature:
            self.next_due = time.time()
            if self.signature is not None:
                self.reset_backoff()
            self.signature = signature

    def reset_backoff(self):
        self.store.set_meta("model_cycle_failures", "0")
        self.store.set_meta("model_retry_after", "0")

    async def tick(self):
        self.reschedule()
        cfg = self.store.settings()
        if (
            cfg.enabled
            and time.time() >= self.next_due
            and time.time() >= float(self.store.meta("model_retry_after") or 0)
            and not self.analyzer.lock.locked()
            and not self.analyzer.running
        ):
            self.next_due = time.time() + cfg.interval_seconds
            started = time.time()
            result = await self.analyzer.cycle()
            if result.get("errors"):
                failures = min(
                    10, int(self.store.meta("model_cycle_failures") or 0) + 1
                )
                self.store.set_meta("model_cycle_failures", str(failures))
                delay = min(3600, cfg.interval_seconds * (2 ** (failures - 1)))
                self.store.set_meta("model_retry_after", str(time.time() + delay))
            elif result.get("calls"):
                self.reset_backoff()
            with self.store.connect() as db:
                more = db.execute(
                    "SELECT 1 FROM events e JOIN objects m ON m.id=e.machine_id AND m.kind='machine' WHERE e.status IN ('pending','capacity','queued') AND NOT coalesce(json_extract(m.data,'$.monitoring_paused'),0) AND NOT coalesce(json_extract(m.data,'$.deletion_pending'),0) LIMIT 1"
                ).fetchone()
                more = (
                    more
                    or db.execute(
                        "SELECT 1 FROM jobs j JOIN objects m ON m.id=j.machine_id AND m.kind='machine' WHERE j.status IN ('pending','retry') AND NOT coalesce(json_extract(m.data,'$.monitoring_paused'),0) AND NOT coalesce(json_extract(m.data,'$.deletion_pending'),0) LIMIT 1"
                    ).fetchone()
                )
            # Under load, use roughly 75% of wall time for work. The configured
            # interval is the upper wait bound, not a forced idle period.
            delay = cfg.interval_seconds
            if cfg.adaptive_batching and more and result.get("calls"):
                delay = min(delay, max(1, (time.time() - started) / 3))
            self.next_due = time.time() + delay

    def state(self):
        self.reschedule()
        cfg = self.store.settings()
        sources = [
            s
            for s in self.store.objects("source")
            if s["enabled"]
            and s["kind"] not in ("metrics", "health")
            and self.store.monitoring_active(s["machine_id"])
        ]
        result = json.loads(self.store.meta("analysis_result") or "{}")
        health = {
            s["id"]: json.loads(self.store.meta("health:" + s["id"]) or "{}")
            for s in sources
        }
        with self.store.connect() as db:
            counts = dict(
                db.execute(
                    "SELECT status,count(*) FROM events WHERE status!='measured' AND source_id NOT IN (SELECT id FROM objects WHERE kind='source' AND json_extract(data,'$.kind') IN ('metrics','health')) GROUP BY status"
                )
            )
            failed = db.execute(
                "SELECT count(*) FROM jobs WHERE status IN ('failed','retry','partial')"
            ).fetchone()[0]
            last_event = db.execute(
                "SELECT max(received) FROM events WHERE status!='measured' AND source_id NOT IN (SELECT id FROM objects WHERE kind='source' AND json_extract(data,'$.kind') IN ('metrics','health'))"
            ).fetchone()[0]
            retry_events = db.execute(
                "SELECT count(*) FROM events WHERE status='error' AND id IN (SELECT value FROM jobs j,json_each(j.event_ids) WHERE j.status='retry' AND j.attempts<3)"
            ).fetchone()[0]
            history = db.execute(
                "SELECT count(*) FROM events WHERE status='capacity' OR status IN ('pending','queued','error') AND received<?",
                (time.time() - max(300, cfg.interval_seconds * 2),),
            ).fetchone()[0]
            recovered = db.execute(
                "SELECT count(DISTINCT e.id) FROM review_batches b JOIN jobs j ON j.id=b.job_id, json_each(b.data,'$.selected') ref JOIN events e ON e.id=ref.value WHERE json_extract(b.data,'$.historical')=1 AND e.status IN ('compact','reviewed') AND j.status NOT IN ('cancelled','split')"
            ).fetchone()[0]
            last_call = db.execute(
                "SELECT created,duration,status FROM usage WHERE kind IN ('analysis','investigation') ORDER BY created DESC LIMIT 1"
            ).fetchone()
            oldest = db.execute(
                "SELECT min(received) FROM events WHERE status IN ('pending','capacity','queued')"
            ).fetchone()[0]
            waiting_jobs = db.execute(
                "SELECT count(*) FROM jobs j JOIN objects m ON m.id=j.machine_id AND m.kind='machine' WHERE j.status IN ('pending','retry') AND NOT coalesce(json_extract(m.data,'$.monitoring_paused'),0) AND NOT coalesce(json_extract(m.data,'$.deletion_pending'),0)"
            ).fetchone()[0]
            eligible = db.execute(
                "SELECT count(*) FROM events e JOIN objects m ON m.id=e.machine_id AND m.kind='machine' WHERE e.status IN ('pending','capacity','queued') AND NOT coalesce(json_extract(m.data,'$.monitoring_paused'),0) AND NOT coalesce(json_extract(m.data,'$.deletion_pending'),0)"
            ).fetchone()[0]
            last_error = db.execute(
                "SELECT error,updated FROM jobs WHERE error IS NOT NULL AND status IN ('failed','retry','partial') ORDER BY updated DESC LIMIT 1"
            ).fetchone()
        retry_after = float(self.store.meta("model_retry_after") or 0)
        due = max(
            self.next_due,
            retry_after,
        )
        queued = (
            counts.get("pending", 0)
            + counts.get("capacity", 0)
            + counts.get("queued", 0)
            + retry_events
        )
        covered = counts.get("compact", 0) + counts.get("reviewed", 0)
        last_review = json.loads(self.store.meta("last_model_review") or "{}")
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
            "next_analysis": (
                due
                if cfg.enabled and self.background and (eligible or waiting_jobs)
                else None
            ),
            "waiting_jobs": waiting_jobs,
            "eligible_queued": eligible,
            "active_call": json.loads(self.store.meta("model_active_call") or "{}"),
            "next_check": due if cfg.enabled and self.background else None,
            "last_scan_started": (
                last_call["created"] - last_call["duration"] if last_call else None
            ),
            "last_scan_finished": last_call["created"] if last_call else None,
            "last_scan_status": last_call["status"] if last_call else None,
            "last_review": last_review,
            "adaptive_batching": cfg.adaptive_batching,
            "batch_tuning": json.loads(self.store.meta("batch_tuning") or "{}"),
            "coverage": dict(
                total=sum(counts.values()),
                represented=counts.get("compact", 0),
                originals=counts.get("reviewed", 0),
                covered=covered,
                unreviewed=sum(counts.values()) - covered,
                queued=queued,
                processing=counts.get("queued", 0),
                history_remaining=history,
                history_recovered=recovered,
                excluded=counts.get("excluded", 0),
                policy=counts.get("sampled", 0),
                errors=counts.get("error", 0),
                retrying=retry_events,
                oversized=counts.get("oversized", 0),
                oldest_pending=oldest,
            ),
            "last_started": self.analyzer.started or result.get("started"),
            "last_finished": self.analyzer.finished or result.get("finished"),
            "last_outcome": self.analyzer.outcome or result.get("outcome"),
            "pending": queued,
            "capacity": counts.get("capacity", 0),
            "error_events": counts.get("error", 0),
            "failed_jobs": failed,
            "last_model_error": dict(last_error) if last_error else None,
            "model_timeout_seconds": cfg.llm.timeout_seconds,
            "retry_after": retry_after if retry_after > time.time() else None,
            "consecutive_failed_cycles": int(
                self.store.meta("model_cycle_failures") or 0
            ),
        }
