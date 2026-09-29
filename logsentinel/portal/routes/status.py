"""Liveness and capacity endpoints."""

from __future__ import annotations

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from ..capacity import capacity_report


def register_status(app, ctx):
    store, health_monitor = ctx.store, ctx.health_monitor

    @app.get("/api/health")
    async def observer_health():
        return dict(
            health_monitor.state(), error=store.meta("health_worker_error") or ""
        )

    @app.get("/api/capacity")
    def capacity(machine_id: str = ""):
        if machine_id and not store.get("machine", machine_id):
            raise HTTPException(404, "Unknown machine")
        return capacity_report(store, machine_id)

    @app.get("/healthz")
    def healthz():
        state = health_monitor.state()["state"]
        return JSONResponse(
            {"status": state}, status_code=200 if state == "ok" else 503
        )
