"""Brain routes: the panel reads and asks, senders deliver with a machine token."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from typing import Literal

import httpx
from fastapi import HTTPException, Request
from pydantic import Field, ValidationError

from logsentinel.redact import redact

from .brain import SYSTEM
from .brain_data import CATEGORIES, BrainConfig, CommandItem, InventoryItem, NoteItem
from .models import Model
from .store import dumps

MAX_ITEMS = 500


class Question(Model):
    message: str = Field(min_length=1, max_length=2000)
    machine_id: str = Field(default="", max_length=100)
    project: str = Field(default="", max_length=500)
    days: int = Field(default=30, ge=1, le=3650)
    language: Literal["en", "es"] = "en"


def register_brain(app, brain, analyzer):
    store, data = brain.store, brain.data

    def machine_exists(id):
        if id and not store.get("machine", id):
            raise HTTPException(404, "Unknown machine")

    def window(days):
        if not 1 <= days <= 3650:
            raise HTTPException(400, "Choose 1–3650 days")

    @app.get("/api/brain")
    def overview():
        return {
            "machines": [
                dict(data.status(m["id"]), name=m["name"], kind=m.get("kind", ""))
                for m in store.objects("machine")
            ]
        }

    @app.get("/api/brain/projects")
    def projects(days: int = 30, machine: str = ""):
        window(days)
        machine_exists(machine)
        return {"projects": data.projects(days, machine)}

    @app.get("/api/brain/days")
    def days_view(days: int = 14, machine: str = ""):
        window(days)
        machine_exists(machine)
        return {"days": data.days(days, machine)}

    @app.get("/api/brain/activity")
    def activity(
        machine: str = "",
        project: str = "",
        q: str = "",
        days: int = 30,
        limit: int = 200,
        before: float | None = None,
    ):
        window(days)
        machine_exists(machine)
        if not 1 <= limit <= 1000 or len(q) > 200 or len(project) > 500:
            raise HTTPException(400, "Use a limit of 1–1000 and a shorter search")
        return {"commands": data.activity(machine, project, q, days, limit, before)}

    @app.get("/api/brain/notes")
    def notes(machine: str = "", project: str = "", q: str = "", days: int = 30, limit: int = 200):
        window(days)
        machine_exists(machine)
        if not 1 <= limit <= 1000 or len(q) > 200 or len(project) > 500:
            raise HTTPException(400, "Use a limit of 1–1000 and a shorter search")
        return {"notes": data.notes(machine, project, q, days, limit)}

    @app.get("/api/brain/changes")
    def changes(machine: str = "", days: int = 30):
        window(days)
        machine_exists(machine)
        return {"changes": data.changes(machine, days)}

    @app.get("/api/brain/{id}/inventory")
    def inventory(id: str, category: str = "", q: str = ""):
        machine_exists(id)
        if not store.get("machine", id):
            raise HTTPException(404, "Unknown machine")
        if category and category not in CATEGORIES or len(q) > 200:
            raise HTTPException(400, "Unknown category")
        return data.inventory(id, category, q)

    @app.post("/api/brain/{id}/config")
    async def configure(id: str, request: Request):
        machine = store.get("machine", id)
        if not machine:
            raise HTTPException(404, "Unknown machine")
        config = BrainConfig.model_validate(
            dict(data.config(id).model_dump(), **await request.json())
        )
        if config.mode == "local" and machine.get("kind") != "local":
            raise HTTPException(400, "Only the central's own machine can be read locally")
        await asyncio.to_thread(data.configure, id, config)
        brain.activity_due = 0.0
        return config.model_dump()

    @app.post("/api/brain/{id}/token")
    def token(id: str):
        if not store.get("machine", id):
            raise HTTPException(404, "Unknown machine")
        value = secrets.token_urlsafe(32)
        store.set_meta("brain_token:" + id, hashlib.sha256(value.encode()).hexdigest())
        store.audit("rotate_brain_token", id)
        return {"token": value, "machine_id": id}

    def prepared(body):
        question = Question.model_validate(body)
        machine_exists(question.machine_id)
        cfg = store.settings()
        payload = brain.context(
            question.message,
            question.machine_id,
            question.project,
            question.days,
            max(2000, min(cfg.input_budget, 48000) - 2000),
        )
        return question, cfg, payload

    @app.post("/api/brain/context")
    async def context(request: Request):
        """What a question would send, for the operator to read first."""
        question, cfg, payload = await asyncio.to_thread(prepared, await request.json())
        return {"payload": payload, "bytes": len(dumps(payload).encode()), "model": cfg.llm.model}

    @app.post("/api/brain/ask")
    async def ask(request: Request):
        from .analysis import ReviewClient, safe_error

        question, cfg, payload = await asyncio.to_thread(prepared, await request.json())
        system = SYSTEM + ("Spanish." if question.language == "es" else "English.")
        async with analyzer.lock:
            try:
                result = await ReviewClient(store).call(
                    payload, kind="brain", machine=question.machine_id, system=system
                )
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                raise HTTPException(
                    502, "Brain question failed: " + safe_error(exc, (cfg.llm.api_key,))
                ) from None
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("answer"), str)
            or len(result["answer"]) > 12000
        ):
            raise HTTPException(502, "Invalid model response")
        return {
            "answer": redact(result["answer"], (cfg.llm.api_key,)),
            "records": {k: len(v) for k, v in payload.items() if isinstance(v, list)},
            "truncated": payload["truncated"],
        }

    register_brain_ingest(app, brain)


def register_brain_ingest(app, brain):
    """Sender-facing reception; safe to mount beside log and metrics ingest."""
    store, data = brain.store, brain.data

    def authorised(id, request):
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        expected = store.meta("brain_token:" + id)
        if not expected or not hmac.compare_digest(
            hashlib.sha256(token.encode()).hexdigest(), expected
        ):
            raise HTTPException(401)
        if not store.monitoring_active(id):
            raise HTTPException(409, "Machine monitoring is paused; retain and retry")
        config = data.config(id)
        if not config.enabled or config.mode != "remote":
            raise HTTPException(409, "Remote brain reports disabled for this machine")
        return config

    def persist(id, config, raw, items):
        retry_after = store.charge_sender_quota(
            "brain:" + id, len(dumps(raw).encode()), len(items), store.settings()
        )
        if retry_after:
            raise HTTPException(
                429,
                "Sender quota spent; retain and retry these records",
                headers={"Retry-After": str(retry_after)},
            )
        usage = store.storage_usage()
        if usage["used_bytes"] >= usage["quota_bytes"] or usage["disk_free_bytes"] < usage["reserve_bytes"]:
            raise HTTPException(507, "Storage full; retain and retry these records")
        now = time.time()
        acknowledged, rejected, commands, notes = [], [], [], []
        for item in items:
            if item.observed > now + 300:
                rejected.append({"id": item.id, "reason": "future"})
            elif item.observed < now - config.retention_days * 86400:
                rejected.append({"id": item.id, "reason": "expired"})
            elif isinstance(item, InventoryItem):
                data.receive_inventory(id, item)
                acknowledged.append(item.id)
            elif isinstance(item, NoteItem):
                # Written on purpose by an agent or a person: kept whenever the
                # brain is on, whether or not typed commands are recorded.
                notes.append(item)
                acknowledged.append(item.id)
            elif config.activity:
                commands.append(item)
                acknowledged.append(item.id)
            else:
                rejected.append({"id": item.id, "reason": "activity_disabled"})
        if commands:
            data.receive_commands(id, commands)
        if notes:
            data.receive_notes(id, notes)
        return {"status": "durable", "acknowledged": acknowledged, "rejected": rejected}

    @app.post("/ingest-brain/{id}")
    async def ingest(id: str, request: Request):
        # Authenticate before the body is read, as log reception does.
        config = await asyncio.to_thread(authorised, id, request)
        raw = await request.json()
        entries = raw.get("items") if isinstance(raw, dict) else None
        if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ITEMS:
            raise HTTPException(400, "Send 1–500 items")
        try:
            kinds: dict[str, type[Model]] = {"inventory": InventoryItem, "note": NoteItem}
            items = [
                kinds.get(str(e.get("kind")) if isinstance(e, dict) else "", CommandItem).model_validate(e)
                for e in entries
            ]
        except ValidationError:
            raise HTTPException(400, "Invalid brain item") from None
        try:
            return await asyncio.to_thread(persist, id, config, raw, items)
        except OSError:
            raise HTTPException(507, "Storage full; retain and retry these records") from None
