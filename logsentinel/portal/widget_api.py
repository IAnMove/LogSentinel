"""Revocable, read-only desktop summary. Never accepts the administrator key."""

import hashlib
import hmac
import secrets
import time

from fastapi import HTTPException, Request
from .rules import redact


def register_widget(app, store, monitor, telemetry, health):
    cache = {"value": None}

    @app.get("/api/widget")
    def configuration():
        return {
            "paired": bool(store.meta("widget_token")),
            "updated": float(store.meta("widget_token_updated") or 0),
        }

    @app.post("/api/widget/token")
    def rotate():
        token = secrets.token_urlsafe(32)
        store.set_meta("widget_token", hashlib.sha256(token.encode()).hexdigest())
        store.set_meta("widget_token_updated", str(time.time()))
        store.audit(
            "rotate_widget_token",
            "Read-only aggregate status; no log or configuration access",
        )
        return {
            "token": token,
            "scope": "widget:read",
            "message": "Shown once; previous widget token is revoked",
        }

    @app.delete("/api/widget/token")
    def revoke():
        store.set_meta("widget_token", "")
        store.audit("revoke_widget_token", "")
        return {"ok": True}

    @app.get("/widget/status")
    def summary(request: Request):
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        expected = store.meta("widget_token")
        if not expected or not hmac.compare_digest(
            hashlib.sha256(token.encode()).hexdigest(), expected
        ):
            raise HTTPException(401)
        previous = cache["value"]
        if previous and time.time() - previous["generated"] < 5:
            return previous
        state = monitor.state()
        with store.connect() as db:
            problems = db.execute(
                "SELECT count(*) FROM problems WHERE status='open'"
            ).fetchone()[0]
        machines = []
        profiles = store.objects("machine")
        for machine in profiles[:100]:
            status = telemetry.status(machine["id"])
            values = status["latest"]["values"] if status["latest"] else {}
            machines.append(
                dict(
                    id=machine["id"],
                    name=redact(machine["name"])[:120],
                    state=status["state"],
                    cpu_pct=values.get("cpu_pct"),
                    ram_pct=values.get("ram_pct"),
                    swap_pct=values.get("swap_pct"),
                    disk_pct=max(
                        (v for k, v in values.items() if k.startswith("disk_pct:")),
                        default=None,
                    ),
                )
            )
        result = dict(
            schema_version=1,
            generated=time.time(),
            health=health.state()["state"],
            capture=state["capture"],
            analysis_enabled=state["analysis_enabled"],
            model_busy=state["model_busy"],
            next_analysis=state["next_analysis"],
            pending=state["pending"],
            capacity=state["capacity"],
            open_problems=problems,
            machines=machines,
            total_machines=len(profiles),
        )
        # Replace the snapshot atomically; another request may still serialize the old one.
        cache["value"] = result
        return result
