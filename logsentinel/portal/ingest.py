"""Log reception, mountable beside the portal or served alone on its own listener.

Administration and reception are different trust boundaries: the portal answers an
operator on loopback, this answers unattended senders that may reach it over the
network. Keeping the routes here lets a deployment expose reception without
exposing the panel that can read and change everything.
"""

from __future__ import annotations
import hashlib
import hmac
import json
import time

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse

from .store import dumps
from .collect import normalize
from .enroll import register_enrollment

# Senders batch up to 500 events of 256 KB, but a well-behaved batch stays far
# below this; it bounds what one unauthenticated request can make us buffer.
MAX_REQUEST_BYTES = 4_000_000


def register_ingest(app, store):
    """Attach the sender-facing routes to an app."""

    def push_source(id, request):
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        expected = store.meta("push:" + id)
        if not expected or not hmac.compare_digest(
            hashlib.sha256(token.encode()).hexdigest(), expected
        ):
            raise HTTPException(401)
        source = store.get("source", id)
        if not source or source["kind"] != "push" or not source["enabled"]:
            raise HTTPException(409, "Source disabled")
        if not store.monitoring_active(source["machine_id"]):
            raise HTTPException(
                409, "Machine monitoring is paused; retain and retry events"
            )
        return source

    @app.post("/heartbeat/{id}")
    async def heartbeat(id: str, request: Request):
        push_source(id, request)
        body = await request.json()
        if (
            not isinstance(body, dict)
            or type(body.get("ok")) is not bool
            or type(body.get("pending")) is not int
            or not 0 <= body["pending"] <= 1000000000
            or set(body) != {"ok", "pending"}
        ):
            raise HTTPException(
                400, "Send ok (boolean) and pending (non-negative integer)"
            )
        old = json.loads(store.meta("health:" + id) or "{}")
        old.update(
            heartbeat=time.time(),
            status="ok" if body["ok"] else "error",
            sender_pending=body["pending"],
            error=(
                ""
                if body["ok"]
                else "Sender capture failed; inspect its spool and permissions"
            ),
        )
        store.set_meta("health:" + id, dumps(old))
        return {"ok": True}

    @app.post("/ingest/{id}")
    async def ingest(id: str, request: Request):
        source = push_source(id, request)
        body = await request.json()
        items = body.get("events", [])
        if not isinstance(items, list) or not 1 <= len(items) <= 500:
            raise HTTPException(400, "Send 1–500 events")
        entries = []
        for item in items:
            if (
                not isinstance(item, dict)
                or not isinstance(item.get("id"), str)
                or not 1 <= len(item["id"]) <= 200
                or not isinstance(item.get("raw"), str)
                or len(item["raw"].encode()) > 256_000
            ):
                raise HTTPException(400, "Invalid event")
            entries.append(normalize(item["raw"], "remote", item["id"]))
        offered = sum(len(item["raw"].encode()) for item in items)
        retry_after = store.charge_sender_quota(
            source["id"], offered, len(items), store.settings()
        )
        if retry_after:
            raise HTTPException(
                429,
                "Sender quota spent; retain and retry these events",
                headers={"Retry-After": str(retry_after)},
            )
        try:
            count = store.ingest(source, entries)
        except OSError:
            raise HTTPException(507, "Storage full; retain and retry these events")
        old_health = json.loads(store.meta("health:" + id) or "{}")
        old_health.update(checked=time.time(), new_events=count)
        if "heartbeat" not in old_health:
            old_health["status"] = "ok"
        store.set_meta("health:" + id, dumps(old_health))
        return {
            "status": "durable",
            "accepted": count,
            "acknowledged": [item["id"] for item in items],
            "quota": store.sender_quota(source["id"], store.settings()),
        }

def create_ingest_app(store):
    """Build a listener carrying reception and nothing else."""
    app = FastAPI(
        title="LogSentinel reception",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store

    @app.middleware("http")
    async def guard(request, call_next):
        # No Host check here: this listener is meant to be reachable by name or
        # address. Authentication is the per-source token, and TLS is the
        # operator's responsibility on the listener itself.
        if request.method in ("POST", "PUT", "PATCH"):
            parts = []
            size = 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_REQUEST_BYTES:
                    return JSONResponse(
                        {"detail": "Request exceeds 4 MB"}, status_code=413
                    )
                parts.append(chunk)
            request._body = b"".join(parts)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    register_ingest(app, store)
    register_enrollment(app, store)
    return app
