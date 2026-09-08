"""Explicit, bounded disk inspection. Never follows links or invokes a shell."""

import asyncio
import time

from fastapi import HTTPException, Request
from pydantic import Field
from .models import Model
from .store import uid


class DiskRequest(Model):
    path: str = Field(min_length=1, max_length=1024)


class DiskScans:
    def __init__(self, store, telemetry):
        self.store, self.telemetry = store, telemetry
        self.tasks = {}

    def recover(self):
        for job in self.store.objects("disk_scan"):
            if job["status"] == "running":
                id = job.pop("id")
                job.update(
                    status="partial",
                    partial=True,
                    reason="interrupted",
                    finished=time.time(),
                )
                self.store.put("disk_scan", job, id)

    def validate(self, machine_id, path):
        machine = self.store.get("machine", machine_id)
        if not machine:
            raise HTTPException(404, "Unknown machine")
        if machine.get("monitoring_paused"):
            raise HTTPException(409, "Machine monitoring is paused")
        cfg = self.telemetry.data.config(machine_id)
        if machine["kind"] != "local" or cfg.mode != "local":
            raise HTTPException(
                400, "Disk inspection is available only on the portal host"
            )
        paths = set(cfg.disk_paths)
        if cfg.discover_disks:
            paths.update(m.mount for m in self.telemetry.sampler.mounts())
        if path not in paths or "\x00" in path:
            raise HTTPException(
                400, "Choose a configured or detected local mount point"
            )

    def start(self, machine_id, path):
        self.validate(machine_id, path)
        for id, (scope, task) in self.tasks.items():
            if scope == machine_id and not task.done():
                return self.store.get("disk_scan", id)
        id = uid()
        data = dict(
            machine_id=machine_id,
            path=path,
            status="running",
            started=time.time(),
            finished=None,
            folders=[],
            total_bytes=None,
            partial=False,
            reason="",
            limit_seconds=15,
        )
        # Keep only the last inspection per mount; this is not filesystem history.
        for old in self.store.objects("disk_scan"):
            if old["machine_id"] == machine_id and old["path"] == path:
                self.store.delete("disk_scan", old["id"])
        self.store.put("disk_scan", data, id)
        task = asyncio.create_task(self.run(id, data))
        self.tasks[id] = (machine_id, task)
        task.add_done_callback(lambda _: self.tasks.pop(id, None))
        return dict(data, id=id)

    async def run(self, id, data):
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                "du",
                "-x",
                "-B1",
                "--max-depth=1",
                "--null",
                "--",
                data["path"],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=65536,
            )

            async def read_sizes():
                seen = 0
                while record := await process.stdout.readuntil(b"\0"):
                    seen += len(record)
                    if seen > 1_000_000:
                        data.update(partial=True, reason="output_limit")
                        break
                    size, path = record[:-1].split(b"\t", 1)
                    path = path.decode(errors="replace")
                    if path.rstrip("/") == data["path"].rstrip("/"):
                        data["total_bytes"] = int(size)
                    else:
                        data["folders"].append(dict(path=path, bytes=int(size)))
                        data["folders"].sort(key=lambda r: r["bytes"], reverse=True)
                        data["folders"] = data["folders"][:30]

            await asyncio.wait_for(read_sizes(), timeout=data["limit_seconds"])
        except asyncio.IncompleteReadError:
            pass
        except (TimeoutError, asyncio.TimeoutError):
            data.update(partial=True, reason="time_limit")
        except (ValueError, asyncio.LimitOverrunError):
            data.update(partial=True, reason="output_limit")
        except FileNotFoundError:
            data.update(partial=True, reason="du_unavailable")
        except asyncio.CancelledError:
            data.update(partial=True, reason="interrupted")
            raise
        except OSError:
            data.update(partial=True, reason="unreadable")
        finally:
            if process:
                if process.returncode is None:
                    if data["partial"]:
                        try:
                            process.kill()
                        except ProcessLookupError:
                            pass
                    await process.wait()
                if process.returncode and not data["reason"]:
                    data.update(partial=True, reason="unreadable")
            data.update(
                status="partial" if data["partial"] else "completed",
                finished=time.time(),
            )
            if self.store.get("machine", data["machine_id"]):
                self.store.put("disk_scan", data, id)

    async def cancel_machine(self, machine_id):
        tasks = [t for scope, t in self.tasks.values() if scope == machine_id]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def close(self):
        tasks = [task for _, task in self.tasks.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def register_disk_info(app, scans):
    @app.post("/api/telemetry/{id}/disk-info", status_code=202)
    async def start(id: str, request: Request):
        body = DiskRequest.model_validate(await request.json())
        return scans.start(id, body.path)

    @app.get("/api/telemetry/{id}/disk-info/{scan_id}")
    def status(id: str, scan_id: str):
        scan = scans.store.get("disk_scan", scan_id)
        if not scan or scan["machine_id"] != id:
            raise HTTPException(404)
        return scan
