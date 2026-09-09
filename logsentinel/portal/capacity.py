"""Read-only, same-window coverage and measured planning; never calls a model."""

import json
import time

from .batch_budget import input_ceiling as model_input_ceiling


def review_signature(cfg):
    """No secrets; comparisons concern workload, not presentation or retention."""
    llm = cfg.get("llm", {})
    return (
        *(
            llm.get(k)
            for k in ("provider", "base_url", "model", "max_tokens", "enable_thinking")
        ),
        *(
            cfg.get(k)
            for k in (
                "context_tokens",
                "input_budget",
                "interval_seconds",
                "max_events",
                "max_calls",
                "sensitivity",
                "adaptive_batching",
                "target_batch_seconds",
                "cycle_budget_seconds",
                "triage_thinking",
                "verification",
            )
        ),
    )


def _window(db, start, end, machine_id):
    where = "received>=? AND received<? AND status!='measured'"
    args = [start, end]
    if machine_id:
        where += " AND machine_id=?"
        args.append(machine_id)
    statuses = {
        r[0]: r[1]
        for r in db.execute(
            "SELECT status,count(*) FROM events WHERE " + where + " GROUP BY status",
            args,
        )
    }
    counts = dict(
        events=sum(statuses.values()),
        reviewed=statuses.get("compact", 0) + statuses.get("reviewed", 0),
        capacity=statuses.get("capacity", 0),
        pending=statuses.get("pending", 0),
        queued=statuses.get("queued", 0),
        oversized=statuses.get("oversized", 0),
        policy=statuses.get("sampled", 0),
        excluded=statuses.get("excluded", 0),
        error=statuses.get("error", 0),
    )
    counts["other"] = counts["events"] - sum(
        v for k, v in counts.items() if k != "events"
    )
    seconds = max(1, end - start)
    return dict(
        start=start,
        end=end,
        window_seconds=seconds,
        **counts,
        incoming_per_minute=counts["events"] * 60 / seconds,
        covered_per_minute=counts["reviewed"] * 60 / seconds,
    )


def capacity_report(store, machine_id=""):
    now = time.time()
    cfg = store.settings()
    sources = store.objects("source")
    signature = review_signature(cfg.model_dump())
    with store.connect() as db:
        hour = _window(db, now - 3600, now, machine_id)
        # A source/rule change also changes volume. Never project an old workload
        # onto a newly selected model or newly filtered source configuration.
        changed = (
            db.execute(
                "SELECT max(created) FROM audit WHERE action IN ('settings','save:source','delete:source','save:rule','delete:rule','save:machine')"
            ).fetchone()[0]
            or 0
        )
        since = max(now - 3600, min(now, changed))
        jobs = []
        for row in db.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT 1000"):
            if row["created"] < since:
                break
            try:
                matches = review_signature(json.loads(row["config"])) == signature
            except (TypeError, ValueError):
                matches = False
            if not matches:
                since = max(since, row["updated"])
                break
            jobs.append(dict(row))
        if len(jobs) == 1000:
            since = max(since, jobs[-1]["created"])
        jobs = [
            j
            for j in jobs
            if j["created"] >= since
            and (not machine_id or j["machine_id"] == machine_id)
        ]
        current = _window(db, min(now, since), now, machine_id)
        done = [
            j for j in jobs if j["status"] in ("done", "partial") and j["attempts"] == 1
        ]
        ids = [j["id"] for j in jobs]
        usage = dict(
            db.execute(
                "SELECT count(*) calls,avg(duration) average_seconds,coalesce(sum(duration),0) seconds,"
                "coalesce(sum(status='error'),0) errors,coalesce(sum(input_tokens),0) input_tokens,"
                "coalesce(sum(output_tokens),0) output_tokens,sum(input_tokens IS NULL OR output_tokens IS NULL) unknown_calls "
                "FROM usage WHERE kind IN ('analysis','investigation') AND job_id IN (SELECT value FROM json_each(?))",
                (json.dumps(ids),),
            ).fetchone()
        )
        # Ignore the still-collecting tail for the planning calculation. These are
        # observed retained-event statuses, not theoretical tokens/s or a promise.
        end = max((j["created"] for j in done), default=since)
        settled = _window(db, min(now, since), min(now, max(since, end)), machine_id)
        services = [
            dict(r)
            for r in db.execute(
                "SELECT machine_id,source_id,service,count(*) events,sum(status='capacity') capacity,"
                "sum(status IN ('compact','reviewed')) reviewed,sum(status='sampled') policy "
                "FROM events WHERE received>=? AND received<? AND status!='measured'"
                + (" AND machine_id=?" if machine_id else "")
                + " GROUP BY machine_id,source_id,service ORDER BY events DESC LIMIT 20",
                [now - 3600, now] + ([machine_id] if machine_id else []),
            )
        ]
        retained_gap = db.execute(
            "SELECT count(*) FROM events WHERE status='capacity'"
            + (" AND machine_id=?" if machine_id else ""),
            [machine_id] if machine_id else [],
        ).fetchone()[0]
    target = settled["events"] - settled["policy"] - settled["excluded"]
    ready = (
        cfg.enabled
        and len(done) >= 2
        and settled["window_seconds"] >= cfg.interval_seconds * 2
        and settled["reviewed"] > 0
    )
    average_batch = (
        (sum(max(0, j["updated"] - j["created"]) for j in done) / len(done))
        if done
        else None
    )
    scoped_machines = [
        m for m in store.objects("machine") if not machine_id or m["id"] == machine_id
    ]
    input_ceiling = min(
        (model_input_ceiling(cfg, m) for m in scoped_machines),
        default=model_input_ceiling(cfg),
    )
    journals = [s for s in sources if s["kind"] == "journald" and s["enabled"]]
    duplicate_journals = (
        journals
        if len(journals) > 1
        and (not machine_id or any(s["machine_id"] == machine_id for s in journals))
        else []
    )
    return dict(
        generated=now,
        **hour,
        services=services,
        analysis=usage,
        retained_capacity=retained_gap,
        current=dict(
            **current, completed_batches=len(done), average_batch_seconds=average_batch
        ),
        planning=dict(
            ready=ready,
            **settled,
            target_per_minute=target * 60 / settled["window_seconds"],
            required_multiplier=(
                target / settled["reviewed"] if ready and settled["capacity"] else None
            ),
        ),
        limits=dict(
            model=cfg.llm.model,
            provider=cfg.llm.provider,
            enabled=cfg.enabled,
            interval_seconds=cfg.interval_seconds,
            context_tokens=cfg.context_tokens,
            output_tokens=cfg.llm.max_tokens,
            input_budget_bytes=cfg.input_budget,
            effective_input_bytes=min(cfg.input_budget, input_ceiling),
            input_ceiling_bytes=input_ceiling,
            suggested_input_bytes=min(500_000, input_ceiling // 512 * 512),
            max_events_per_machine=cfg.max_events,
            max_calls_per_cycle=cfg.max_calls,
            active_machines=len(
                {
                    s["machine_id"]
                    for s in sources
                    if s["enabled"] and s["kind"] not in ("metrics", "health")
                }
            ),
        ),
        duplicate_journals=[
            {k: s[k] for k in ("id", "machine_id", "name")} for s in duplicate_journals
        ],
    )
