"""Authenticated telemetry configuration and machine-bound remote ingestion."""

import asyncio
import hashlib
import hmac
import secrets
import time
from typing import Literal

from fastapi import Request, HTTPException
from pydantic import Field
from .models import Model
from .telemetry_data import MetricSample, TelemetryConfig


class TrendRequest(Model):
    language: Literal["en", "es"] = "en"
    days: Literal[1, 7, 30] = 1


class SampleBatch(Model):
    samples: list[MetricSample] = Field(min_length=1, max_length=20)


def register_telemetry(app, telemetry):
    store = telemetry.store

    def machine_exists(id):
        if not store.get("machine", id):
            raise HTTPException(404, "Unknown machine")

    @app.get("/api/telemetry")
    def overview():
        return {
            "machines": [telemetry.status(m["id"]) for m in store.objects("machine")],
            "error": store.meta("telemetry_worker_error") or "",
        }

    @app.get("/api/telemetry/{id}")
    def history(id: str, days: int = 7, hours: int = 1):
        machine_exists(id)
        if not 1 <= days <= 365:
            raise HTTPException(400, "Choose 1–365 days")
        if hours not in (1, 6, 24):
            raise HTTPException(400, "Choose 1, 6 or 24 hours")
        return dict(
            telemetry.status(id),
            hourly=telemetry.data.rollups(id),
            daily=telemetry.data.rollups(id, "day", days),
            recent=telemetry.data.recent(id, hours),
            timezone="UTC",
            analyses=[
                j for j in store.objects("metric_analysis") if j["machine_id"] == id
            ][-10:],
        )

    @app.post("/api/telemetry/{id}/config")
    async def configure(id: str, request: Request):
        machine_exists(id)
        cfg = TelemetryConfig.model_validate(
            dict(telemetry.data.config(id).model_dump(), **await request.json())
        )
        await asyncio.to_thread(telemetry.configure, id, cfg)
        return cfg.model_dump()

    @app.post("/api/telemetry/{id}/analyze")
    async def analyze(id: str, request: Request):
        machine_exists(id)
        options = TrendRequest.model_validate(await request.json())
        return telemetry.enqueue(id, options.language, options.days)

    @app.post("/api/telemetry/{id}/token")
    def token(id: str):
        machine_exists(id)
        if telemetry.data.config(id).mode != "remote":
            raise HTTPException(400, "Select remote measurements first")
        value = secrets.token_urlsafe(32)
        store.set_meta(
            "telemetry_token:" + id, hashlib.sha256(value.encode()).hexdigest()
        )
        store.audit("rotate_telemetry_token", id)
        return {"token": value, "machine_id": id}

    @app.post("/ingest-metrics/{id}")
    async def ingest(id: str, request: Request):
        token = request.headers.get("authorization", "").removeprefix("Bearer ")
        expected = store.meta("telemetry_token:" + id)
        if not expected or not hmac.compare_digest(
            hashlib.sha256(token.encode()).hexdigest(), expected
        ):
            raise HTTPException(401)
        cfg = telemetry.data.config(id)
        if not cfg.enabled or cfg.mode != "remote":
            raise HTTPException(409, "Remote metrics disabled")
        body = SampleBatch.model_validate(await request.json())
        accepted = 0
        acknowledged, rejected = [], []
        if any(sample.observed > time.time() + 60 for sample in body.samples):
            raise HTTPException(
                400, "Metric timestamp is more than 60 seconds in the future"
            )
        try:
            for sample in body.samples:
                if sample.observed < time.time() - cfg.retention_days * 86400:
                    rejected.append({"id": sample.id, "reason": "expired"})
                    continue
                accepted += await asyncio.to_thread(telemetry.receive, id, sample)
                acknowledged.append(sample.id)
        except OSError:
            raise HTTPException(507, "Storage full; retain and retry these samples")
        return {
            "status": "durable",
            "accepted": accepted,
            "acknowledged": acknowledged,
            "rejected": rejected,
        }
