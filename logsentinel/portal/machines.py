"""Machine lifecycle: scoped pause and confirmed, durable deletion jobs."""

import asyncio
import json
import sqlite3
import time

from fastapi import HTTPException, Request
from pydantic import Field
from .models import Model
from .store import dumps


class PauseRequest(Model):
    paused: bool


class DeleteRequest(Model):
    confirm_name: str = Field(min_length=1, max_length=120)


def deletion_preview(store, machine_id):
    machine = store.get("machine", machine_id)
    if not machine:
        raise HTTPException(404, "Unknown machine")
    with store.connect() as db:
        counts = {
            table: db.execute(
                f"SELECT count(*) FROM {table} WHERE machine_id=?", (machine_id,)
            ).fetchone()[0]
            for table in (
                "events",
                "problems",
                "jobs",
                "usage",
                "telemetry_samples",
                "telemetry_rollups",
            )
        }
    sources = {
        s["id"] for s in store.objects("source") if s["machine_id"] == machine_id
    }
    counts["sources"] = len(sources)
    counts["destinations"] = sum(
        d.get("machine_id") == machine_id or d.get("source_id") in sources
        for d in store.objects("destination")
    )
    counts["conversations"] = sum(
        c.get("machine_id") == machine_id for c in store.objects("chat")
    )
    return dict(machine_id=machine_id, name=machine["name"], counts=counts)


def erase_machine(store, machine_id):
    """All retained evidence and scoped configuration in a single transaction."""
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        source_ids = {
            r[0]
            for r in db.execute(
                "SELECT id FROM objects WHERE kind='source' AND json_extract(data,'$.machine_id')=?",
                (machine_id,),
            )
        }
        problem_ids = {
            r[0]
            for r in db.execute(
                "SELECT id FROM problems WHERE machine_id=?", (machine_id,)
            )
        }
        scoped_ids = {machine_id, "telemetry:" + machine_id, *source_ids, *problem_ids}
        for row in db.execute("SELECT * FROM objects").fetchall():
            data = json.loads(row["data"])
            if row["kind"] == "machine_deletion":
                continue
            if (
                row["id"] in scoped_ids
                or data.get("machine_id") == machine_id
                or data.get("source_id") in source_ids
                or data.get("problem_id") in problem_ids
                or (
                    row["kind"] == "rule"
                    and data.get("kind") == "problem"
                    and data.get("pattern") in problem_ids
                )
            ):
                scoped_ids.add(row["id"])
        placeholders = dumps(list(scoped_ids))
        db.execute(
            "DELETE FROM deliveries WHERE destination_id IN (SELECT value FROM json_each(?)) OR problem_id IN (SELECT id FROM problems WHERE machine_id=?)",
            (placeholders, machine_id),
        )
        for table in ("appearances", "revisions"):
            db.execute(
                f"DELETE FROM {table} WHERE problem_id IN (SELECT id FROM problems WHERE machine_id=?)",
                (machine_id,),
            )
        for table in ("cursors", "metrics", "segments"):
            # Include orphaned source identities from old evidence too.
            db.execute(
                f"DELETE FROM {table} WHERE source_id IN (SELECT value FROM json_each(?)) OR source_id IN (SELECT source_id FROM events WHERE machine_id=?)",
                (dumps(list(source_ids)), machine_id),
            )
        for table in (
            "events",
            "problems",
            "jobs",
            "usage",
            "telemetry_samples",
            "telemetry_rollups",
            "telemetry_alerts",
        ):
            db.execute(f"DELETE FROM {table} WHERE machine_id=?", (machine_id,))
        db.execute(
            "DELETE FROM objects WHERE id IN (SELECT value FROM json_each(?))",
            (placeholders,),
        )
        db.execute(
            "DELETE FROM audit WHERE object_id IN (SELECT value FROM json_each(?))",
            (placeholders,),
        )
        for row in db.execute("SELECT key,value FROM meta").fetchall():
            if any(id in row["key"].split(":") for id in scoped_ids) or (
                row["key"].startswith("health_condition:")
                and any(id in row["value"] for id in scoped_ids)
            ):
                db.execute("DELETE FROM meta WHERE key=?", (row["key"],))
        # A stale collector/sender must never recreate retained events after deletion.
        db.execute(
            "INSERT OR REPLACE INTO meta VALUES(?,?)",
            ("deleted_machine:" + machine_id, str(time.time())),
        )
    store.audit(
        "delete_machine",
        machine_id,
        "Retained data removed; original source files and backups unchanged",
    )


class MachineLifecycle:
    def __init__(
        self, store, analyzer, collector, telemetry, health, outbox, scans, chats
    ):
        self.store, self.analyzer, self.collector = store, analyzer, collector
        self.telemetry, self.health, self.outbox = telemetry, health, outbox
        self.scans, self.chats, self.tasks = scans, chats, {}

    def job(self, machine_id):
        return self.store.get("machine_deletion", "delete:" + machine_id)

    def save(self, machine_id, **changes):
        data = self.job(machine_id) or dict(machine_id=machine_id, created=time.time())
        data.pop("id", None)
        data.update(changes, updated=time.time())
        self.store.put("machine_deletion", data, "delete:" + machine_id)
        return dict(data, id="delete:" + machine_id)

    async def pause(self, machine_id, paused):
        def apply():
            with self.collector.lock, self.telemetry.lock, self.health.lock:
                machine = self.store.get("machine", machine_id)
                if not machine:
                    raise HTTPException(404, "Unknown machine")
                if machine.get("deletion_pending"):
                    raise HTTPException(409, "Machine deletion is pending")
                machine.pop("id")
                machine["monitoring_paused"] = paused
                self.store.put("machine", machine, machine_id)
                for source in self.store.objects("source"):
                    if source["machine_id"] == machine_id:
                        self.store.set_meta(
                            "health_since:source:" + source["id"], str(time.time())
                        )
                        if paused:
                            self.collector._poll(dict(source, enabled=False))
                self.store.set_meta(
                    "health_since:metrics:" + machine_id, str(time.time())
                )
                self.telemetry.next_sample.pop(machine_id, None)
                if self.telemetry.data.config(machine_id).mode == "local":
                    self.telemetry.sampler.previous_cpu = None
                    self.telemetry.sampler.previous_threads = {}
                return dict(machine, id=machine_id)

        return await asyncio.to_thread(apply)

    async def request_delete(self, machine_id, confirm_name):
        machine = self.store.get("machine", machine_id)
        if not machine:
            raise HTTPException(404, "Unknown machine")
        if confirm_name != machine["name"]:
            raise HTTPException(409, "Machine name changed; review deletion again")
        # Persist intent first so restart recovery finishes an already confirmed deletion.
        if machine_id not in self.tasks:
            self.save(machine_id, status="queued", error="")
            self.start(machine_id)
        return self.job(machine_id)

    def start(self, machine_id):
        if machine_id in self.tasks:
            return
        task = asyncio.create_task(self.run(machine_id))
        self.tasks[machine_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(machine_id, None))

    async def run(self, machine_id):
        try:
            machine = self.store.get("machine", machine_id)
            if machine:
                machine.pop("id")
                machine.update(monitoring_paused=True, deletion_pending=True)
                self.store.put("machine", machine, machine_id)
            for job in self.store.objects("chat_request"):
                if job["machine_id"] == machine_id and job["status"] == "queued":
                    self.chats.cancel(job["id"])
            await self.scans.cancel_machine(machine_id)
            self.save(machine_id, status="waiting", error="")
            # Let requests already sent finish before removing their evidence and results.
            async with self.analyzer.lock, self.outbox.lock:
                self.save(machine_id, status="deleting")
                reclaimed = await asyncio.to_thread(self.erase, machine_id)
            self.save(
                machine_id,
                status="completed",
                finished=time.time(),
                space_reclaimed=reclaimed,
            )
        except asyncio.CancelledError:
            self.save(machine_id, status="queued")
            raise
        except Exception as exc:
            self.save(
                machine_id,
                status="failed",
                error=type(exc).__name__ + ": deletion failed; retry from Machines",
            )

    def erase(self, machine_id):
        with self.collector.lock, self.telemetry.lock, self.health.lock:
            for source in self.store.objects("source"):
                if source["machine_id"] == machine_id:
                    self.collector._poll(dict(source, enabled=False))
            erase_machine(self.store, machine_id)
            self.telemetry.next_sample.pop(machine_id, None)
            self.health.snapshot["checks"] = [
                c
                for c in self.health.snapshot["checks"]
                if c["machine_id"] != machine_id
            ]
            # Reclaim pages so deleting data also restores the configured disk quota.
            try:
                with self.store.connect() as db:
                    db.execute("VACUUM")
                    db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error:
                # Logical deletion already committed; never report that data still exists.
                return False
            return True

    def recover(self):
        for job in self.store.objects("machine_deletion"):
            if job["status"] in ("queued", "waiting", "deleting"):
                self.start(job["machine_id"])

    async def close(self):
        tasks = list(self.tasks.values())
        # SQLite deletion runs in a thread: finish that transaction before shutdown.
        for task in tasks:
            if not any(
                j["status"] == "deleting" and self.tasks.get(j["machine_id"]) is task
                for j in self.store.objects("machine_deletion")
            ):
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def register_machines(app, lifecycle):
    @app.post("/api/machines/{id}/monitoring")
    async def pause(id: str, request: Request):
        body = PauseRequest.model_validate(await request.json())
        return await lifecycle.pause(id, body.paused)

    @app.get("/api/machines/{id}/delete-preview")
    def preview(id: str):
        return deletion_preview(lifecycle.store, id)

    @app.post("/api/machines/{id}/delete", status_code=202)
    async def delete(id: str, request: Request):
        body = DeleteRequest.model_validate(await request.json())
        return await lifecycle.request_delete(id, body.confirm_name)

    @app.get("/api/machines/{id}/deletion")
    def status(id: str):
        job = lifecycle.job(id)
        if not job:
            raise HTTPException(404)
        return job
