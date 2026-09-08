"""Reviewable capacity proposals from retained logs and measured model work."""

import asyncio
import hashlib
import json
import math
from statistics import median
import time
from typing import Literal

from fastapi import HTTPException, Request
from .analysis import Analyzer, compact, SYSTEM
from .capacity import review_signature
from .model_timing import estimate_model_time, endpoint_id
from .models import Model, Settings, Source
from .rules import excluded
from .store import dumps


def fingerprint(store):
    return hashlib.sha256(
        dumps(
            dict(
                settings=store.settings().model_dump(),
                sources=store.objects("source"),
                rules=store.objects("rule"),
                machines=store.objects("machine"),
            )
        ).encode()
    ).hexdigest()


def measured_capacity(store, cfg, machine_id=""):
    """Use successful completed batches with the current model and budgets."""
    durations, covered, calls = [], [], []
    with store.connect() as db:
        changed = db.execute(
            "SELECT coalesce(max(created),0) FROM audit WHERE action IN ('settings','save:source','delete:source','save:rule','delete:rule')"
        ).fetchone()[0]
        jobs = db.execute(
            "SELECT * FROM jobs WHERE status='done' AND attempts=1 AND created>? ORDER BY created DESC LIMIT 100",
            (max(time.time() - 86400, changed),),
        ).fetchall()
        for job in jobs:
            if review_signature(json.loads(job["config"])) != review_signature(
                cfg.model_dump()
            ):
                continue
            use = db.execute(
                "SELECT * FROM usage WHERE job_id=? AND kind IN ('analysis','investigation')",
                (job["id"],),
            ).fetchall()
            if not use or any(r["status"] != "ok" or r["duration"] <= 0 for r in use):
                continue
            if any(
                json.loads(r["detail"]).get("endpoint_id", endpoint_id(cfg))
                != endpoint_id(cfg)
                for r in use
            ):
                continue
            n = db.execute(
                "SELECT count(*) FROM events WHERE id IN (SELECT value FROM json_each(?)) AND status IN ('compact','reviewed')",
                (job["event_ids"],),
            ).fetchone()[0]
            if not n:
                continue
            durations.append(sum(r["duration"] for r in use))
            covered.append(n)
            calls.append(len(use))
            if len(durations) == 12:
                break
        recent = db.execute(
            "SELECT status,detail FROM usage WHERE kind IN ('analysis','investigation') ORDER BY created DESC LIMIT 100"
        ).fetchall()
    matching = [
        r
        for r in recent
        if (d := json.loads(r["detail"])).get("model") == cfg.llm.model
        and d.get("provider") == cfg.llm.provider
        and d.get("endpoint_id", endpoint_id(cfg)) == endpoint_id(cfg)
    ][:12]
    error_rate = (
        sum(r["status"] != "ok" for r in matching) / len(matching) if matching else None
    )
    active = {
        s["machine_id"]
        for s in store.objects("source")
        if s["enabled"]
        and s["kind"] not in ("metrics", "health")
        and store.monitoring_active(s["machine_id"])
    }
    if machine_id:
        active.add(machine_id)  # Include this machine's share if it is later resumed.
    hosts = max(1, len(active))
    seconds = median(durations) if durations else None
    batch_calls = median(calls) if calls else None
    period = (
        max(
            cfg.interval_seconds
            * math.ceil(hosts / max(1, cfg.max_calls / batch_calls)),
            hosts * seconds,
        )
        if seconds
        else None
    )
    reliable = len(durations) >= 3 and error_rate is not None and error_rate < 0.25
    return dict(
        batches=len(durations),
        batch_seconds=seconds,
        events_per_batch=median(covered) if covered else None,
        calls_per_batch=batch_calls,
        active_machines=hosts,
        seconds_per_machine_batch=period,
        events_per_minute=(median(covered) * 60 / period * 0.75) if reliable else None,
        error_rate=error_rate,
        headroom_percent=25,
        reliable=reliable,
    )


def propose(store, machine_id):
    machine = store.get("machine", machine_id)
    if not machine:
        raise HTTPException(404, "Unknown machine")
    if machine.get("deletion_pending"):
        raise HTTPException(409, "Machine deletion is pending")
    before = fingerprint(store)
    cfg = store.settings()
    sources = [
        s
        for s in store.objects("source")
        if s["machine_id"] == machine_id
        and s["enabled"]
        and s["kind"] not in ("metrics", "health")
    ]
    now = time.time()
    with store.connect() as db:
        ids = [
            r[0]
            for r in db.execute(
                "SELECT id FROM events WHERE source_id IN (SELECT value FROM json_each(?)) AND received>? AND status!='measured' ORDER BY received DESC,rowid DESC LIMIT 2000",
                (dumps([s["id"] for s in sources]), now - 3600),
            )
        ]
        total, first = db.execute(
            "SELECT count(*),min(received) FROM events WHERE source_id IN (SELECT value FROM json_each(?)) AND received>? AND status!='measured'",
            (dumps([s["id"] for s in sources]), now - 3600),
        ).fetchone()
    events = store.events(ids=ids, limit=2000)
    window = max(60, now - (first or now))
    eligible = [e for e in events if not excluded(store, e)]
    capacity = measured_capacity(store, cfg, machine_id)
    rate = total * 60 / window
    choices = []
    ceiling = max(
        0, cfg.context_tokens - cfg.llm.max_tokens - len(SYSTEM.encode()) - 1024
    )

    def option(id, patches, global_patch=None):
        global_patch = global_patch or {}
        selected = []
        for source in sources:
            proposed = dict(source, **patches.get(source["id"], {}))
            chosen, _ = Analyzer._trigger_events(
                [e for e in eligible if e["source_id"] == source["id"]], proposed
            )
            selected.extend(chosen)
        fraction = len(selected) / len(events) if events else 0
        target = rate * fraction
        groups, packed, omitted = compact(
            selected[: global_patch.get("max_events", cfg.max_events)],
            min(global_patch.get("input_budget", cfg.input_budget), ceiling),
        )
        prediction = capacity["events_per_minute"]
        # Workload changes and omitted context cannot be certified against old timing.
        contexts = any(
            dict(s, **patches.get(s["id"], {})).get("context_minutes", 5) > 0
            and dict(s, **patches.get(s["id"], {})).get("analysis_mode", "all") != "all"
            for s in sources
        )
        fits = (
            target <= prediction
            if prediction is not None and events and not global_patch and not contexts
            else None
        )
        choices.append(
            dict(
                id=id,
                source_patches=patches,
                global_patch=global_patch,
                triggers=len(selected),
                omitted_by_policy=len(eligible) - len(selected),
                retained_fraction=fraction,
                selected_per_minute=target,
                fits_estimate=fits,
                context_extra=contexts,
                groups_in_trial=len(groups),
                events_in_trial=len(packed),
                outside_trial=len(selected) - len(packed),
            )
        )

    option("current", {})
    terms = Source(machine_id="", name="defaults", kind="push").trigger_terms
    for id, level, keywords in (
        ("warnings", 4, terms),
        (
            "errors",
            3,
            "error\ncritical\nfailed\nfailure\npanic\nexception\nunauthorized\npermission denied\nout of memory\nno space left on device",
        ),
        (
            "critical",
            2,
            "critical\nfatal\npanic\nout of memory\nno space left on device\nsegfault\nsegmentation fault\nunauthorized",
        ),
    ):
        option(
            id,
            {
                s["id"]: dict(
                    analysis_mode="priority",
                    priority_ceiling=level,
                    trigger_terms=keywords,
                    context_minutes=0,
                )
                for s in sources
            },
        )
    # A larger payload stays inside the already configured context; requires remeasurement.
    suggested = min(
        500_000, ceiling, max(cfg.input_budget, int(cfg.input_budget * 1.5))
    )
    if suggested > cfg.input_budget:
        option("larger_batch", {}, dict(input_budget=suggested))
    # A shorter interval only helps when the measured workload leaves spare time.
    if capacity["reliable"] and capacity["batch_seconds"]:
        interval = max(
            5, math.ceil(capacity["batch_seconds"] * capacity["active_machines"] * 1.25)
        )
        if interval < cfg.interval_seconds * 0.8:
            option("more_frequent", {}, dict(interval_seconds=interval))
    recommended = next((o["id"] for o in choices if o["fits_estimate"] is True), None)
    if before != fingerprint(store):
        raise HTTPException(
            409, "Configuration changed during inspection; generate a new proposal"
        )
    plan = dict(
        machine_id=machine_id,
        created=now,
        fingerprint=before,
        model=cfg.llm.model,
        sample_size=len(events),
        sample_limit=2000,
        events_in_window=total,
        window_seconds=window,
        sample_truncated=total > len(events),
        incoming_per_minute=rate,
        excluded=len(events) - len(eligible),
        capacity=capacity,
        timing=estimate_model_time(store, "analysis"),
        choices=choices,
        recommended=recommended,
        current=dict(
            interval_seconds=cfg.interval_seconds,
            input_budget=cfg.input_budget,
            context_tokens=cfg.context_tokens,
            max_events=cfg.max_events,
            enabled=cfg.enabled,
        ),
        sources=[{k: s[k] for k in ("id", "name", "kind")} for s in sources],
        applied=False,
    )
    # Persist numeric previews and exact changes, not another copy of the raw logs.
    for old in store.objects("optimization")[:-29]:
        store.delete("optimization", old["id"])
    id = store.put("optimization", plan)
    return dict(plan, id=id)


class ApplyRequest(Model):
    plan_id: str
    choice: Literal["warnings", "errors", "critical", "larger_batch", "more_frequent"]
    acknowledge_coverage: bool = False
    acknowledge_global: bool = False


def apply_plan(store, machine_id, body):
    plan = store.get("optimization", body.plan_id)
    if not plan or plan["machine_id"] != machine_id:
        raise HTTPException(404, "Unknown proposal")
    if plan["applied"] or time.time() - plan["created"] > 900:
        raise HTTPException(409, "Proposal already applied or expired; inspect again")
    choice = next((o for o in plan["choices"] if o["id"] == body.choice), None)
    if not choice:
        raise HTTPException(400, "Unavailable proposal")
    if not body.acknowledge_coverage or (
        choice["global_patch"] and not body.acknowledge_global
    ):
        raise HTTPException(
            400, "Review coverage and acknowledge changes to all machines"
        )
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        latest = store.get("optimization", body.plan_id)
        if not latest or latest["applied"]:
            raise HTTPException(409, "Proposal already applied or removed")
        if fingerprint(store) != plan["fingerprint"]:
            raise HTTPException(409, "Configuration changed; generate a new proposal")
        for id, patch in choice["source_patches"].items():
            source = store.get("source", id)
            source.pop("id")
            data = Source.model_validate(dict(source, **patch)).model_dump()
            db.execute(
                "UPDATE objects SET data=? WHERE kind='source' AND id=?",
                (dumps(data), id),
            )
            db.execute(
                "INSERT INTO audit(created,action,object_id,detail) VALUES(?,?,?,?)",
                (time.time(), "save:source", id, "Reviewed optimization"),
            )
        if choice["global_patch"]:
            settings = Settings.model_validate(
                dict(store.settings().model_dump(), **choice["global_patch"])
            )
            db.execute(
                "UPDATE meta SET value=? WHERE key='settings'",
                (settings.model_dump_json(),),
            )
            db.execute(
                "INSERT INTO audit(created,action,object_id,detail) VALUES(?,?,?,?)",
                (time.time(), "settings", "", "Reviewed optimization"),
            )
        plan.pop("id", None)
        plan.update(applied=True, applied_at=time.time(), choice=body.choice)
        db.execute(
            "UPDATE objects SET data=? WHERE id=? AND kind='optimization'",
            (dumps(plan), body.plan_id),
        )
        db.execute(
            "INSERT INTO audit(created,action,object_id,detail) VALUES(?,?,?,?)",
            (time.time(), "apply_optimization", machine_id, body.choice),
        )
    return dict(ok=True, choice=body.choice, verification_required=True)


def register_optimizer(app, store, monitor):
    @app.post("/api/machines/{id}/optimize")
    async def preview(id: str):
        return await asyncio.to_thread(propose, store, id)

    @app.post("/api/machines/{id}/optimize/apply")
    async def apply(id: str, request: Request):
        body = ApplyRequest.model_validate(await request.json())
        result = await asyncio.to_thread(apply_plan, store, id, body)
        monitor.reschedule()
        return result
