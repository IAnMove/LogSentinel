"""Machines, sources, destinations and rules, the events they hold and the overview."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import time
from pathlib import Path

from fastapi import HTTPException, Request

from ..models import Rule, Source, merge_destination
from ..rules import (
    protected_secrets,
    sanitize,
    validate_rule,
)
from .common import MODELS, public
from .model import setup_state


def register_objects(app, ctx):
    store, collector, monitor, telemetry, build = (
        ctx.store,
        ctx.collector,
        ctx.monitor,
        ctx.telemetry,
        ctx.build,
    )

    @app.get("/api/state")
    def state():
        objects = {
            kind: [public(kind, o) for o in store.objects(kind)] for kind in MODELS
        }
        settings = store.settings().model_dump()
        settings["llm"]["api_key_set"] = bool(settings["llm"].pop("api_key"))
        health = {
            s["id"]: json.loads(store.meta("health:" + s["id"]) or "{}")
            for s in objects["source"]
        }
        return dict(
            objects,
            settings=settings,
            build=build,
            monitor=dict(monitor.state(), build=build),
            setup=setup_state(store),
            defaults={
                "source": Source(
                    machine_id="", name="source", kind="journald"
                ).model_dump()
            },
            health=health,
            stats=store.stats(),
            worker_error=store.meta("worker_error"),
            last_analysis=store.meta("last_analysis"),
            problems=store.rows("problems"),
            jobs=store.rows("jobs", 30),
            deliveries=store.rows("deliveries", 50),
        )

    def scoped(kind, data):
        machine = data.get("machine_id")
        source = data.get("source_id")
        if machine and not store.get("machine", machine):
            raise HTTPException(400, "Unknown machine")
        if machine and store.get("machine", machine).get("deletion_pending"):
            raise HTTPException(409, "Machine deletion is pending")
        if source:
            obj = store.get("source", source)
            if not obj or (machine and obj["machine_id"] != machine):
                raise HTTPException(400, "Source does not belong to machine")
        warning = ""
        if kind == "rule":
            validate_rule(Rule(**data))
        if kind == "source" and data["kind"] in ("file", "folder"):
            from ..source_paths import validate_source_path

            path = validate_source_path(data["path"], store.directory)
            unusual = any(
                path == Path(root) or path.is_relative_to(root)
                for root in ("/etc", "/root", "/proc", "/sys", "/dev")
            )
            if unusual:
                warning = "Esta ruta no es un sitio típico de logs. El proceso leerá lo que pueda abrir."
            data["path"] = str(path)
        return data, warning

    @app.post("/api/objects/{kind}")
    async def save_object(kind: str, request: Request):
        if kind not in MODELS:
            raise HTTPException(404)
        body = await request.json()
        id = body.pop("id", None)
        clear = body.pop("clear_secrets", [])
        body.pop("configured_fields", None)
        old = store.get(kind, id) if id else None
        if id and old is None:
            raise HTTPException(404)
        if kind == "machine" and any(
            k in body and body[k] != (old or {}).get(k, False)
            for k in ("deletion_pending", "monitoring_paused")
        ):
            raise HTTPException(400, "Use the machine monitoring or deletion controls")
        if old and old.get("deletion_pending"):
            raise HTTPException(409, "Machine deletion is pending")
        if old:
            old.pop("id")
            merged = dict(old, **body)
            if kind == "destination":
                merged = merge_destination(old, body, clear)
            body = merged
        data = MODELS[kind](**body).model_dump()
        if kind == "machine" and old and data["kind"] != "local":
            metrics_cfg = telemetry.data.config(id)
            if metrics_cfg.enabled and metrics_cfg.mode == "local":
                raise HTTPException(
                    400,
                    "Disable local metrics before changing this machine to imported",
                )
        if kind == "source" and (
            data["kind"] in ("metrics", "health")
            or (old and old["kind"] in ("metrics", "health"))
        ):
            raise HTTPException(400, "Manage this source in Metrics or Health")
        data, warning = scoped(kind, data)
        if kind == "source" and data["kind"] == "journald" and data["enabled"]:
            if any(
                s["kind"] == "journald" and s["enabled"] and s["id"] != id
                for s in store.objects("source")
            ):
                raise HTTPException(
                    409,
                    "An enabled source already captures this local journal. Reuse it or disable it before enabling another.",
                )
        if kind == "source" and old and data["machine_id"] != old["machine_id"]:
            raise HTTPException(
                400,
                "Create a new source to change machine identity; existing evidence retains its origin",
            )
        if (
            kind == "rule"
            and data["kind"] == "problem"
            and not store.problem(data["pattern"])
        ):
            raise HTTPException(400, "Unknown problem")
        id = store.put(kind, data, id)
        if kind == "source" and (not old or not old["enabled"] and data["enabled"]):
            store.set_meta("health_since:source:" + id, str(time.time()))
        result = public(kind, dict(data, id=id))
        if warning:
            result["warning"] = warning
        return result

    @app.delete("/api/objects/{kind}/{id}")
    def remove(kind: str, id: str):
        if kind not in MODELS or not store.get(kind, id):
            raise HTTPException(404)
        if kind in ("source", "machine"):
            raise HTTPException(
                400,
                "Disable sources to preserve evidence; deletion of retained evidence uses the retention policy",
            )
        store.delete(kind, id)
        return {"ok": True}

    @app.post("/api/source/{id}/poll")
    async def poll(id: str):
        source = store.get("source", id)
        if not source:
            raise HTTPException(404)
        if not store.monitoring_active(source["machine_id"]):
            raise HTTPException(409, "Machine monitoring is paused")
        if source["kind"] == "push":
            raise HTTPException(400, "Push sources receive events from a sender")
        count = await asyncio.to_thread(collector.poll, dict(source, enabled=True))
        return {
            "events": count,
            "health": json.loads(store.meta("health:" + id) or "{}"),
        }

    @app.get("/api/events")
    def events(
        machine_id: str = "",
        source_id: str = "",
        status: str = "",
        q: str = "",
        offset: int = 0,
        limit: int = 100,
    ):
        limit = min(max(limit, 1), 500)
        cursor = max(0, offset)
        rows = []
        scanned = 0
        exhausted = False
        while len(rows) < limit and scanned < 5000:
            chunk = store.events(
                machine_id,
                source_id,
                status,
                min(limit - len(rows), 5000 - scanned),
                cursor,
            )
            if not chunk:
                exhausted = True
                break
            cursor += len(chunk)
            scanned += len(chunk)
            rows.extend(
                e
                for e in chunk
                if not q or q.casefold() in e.get("message", "").casefold()
            )
        return {
            "events": sanitize(rows, protected_secrets(store)),
            "search_scope": "retained events",
            "offset": offset,
            "next_offset": cursor,
            "scanned": scanned,
            "exhausted": exhausted,
        }

    @app.get("/api/stats")
    def stats(machine_id: str = ""):
        return store.stats(machine_id)

    @app.post("/api/sources/{id}/token")
    def source_token(id: str):
        source = store.get("source", id)
        if not source or source["kind"] != "push":
            raise HTTPException(400, "Select a push source")
        token = secrets.token_urlsafe(32)
        store.set_meta("push:" + id, hashlib.sha256(token.encode()).hexdigest())
        store.audit("rotate_source_token", id)
        return {
            "token": token,
            "source_id": id,
            "message": "Shown once. Previous token is now invalid.",
        }
