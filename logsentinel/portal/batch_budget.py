"""Conservative byte ceilings, with bounded adaptation to measured model time."""

import hashlib
import json
from statistics import median

from .store import dumps


def input_ceiling(cfg, machine=None):
    from .analysis import TRIAGE_SYSTEM

    machine = machine or {}
    envelope = dumps(
        dict(
            machine={
                k: machine.get(k, "") for k in ("name", "os", "timezone", "notes")
            },
            sensitivity=cfg.sensitivity,
            groups=[],
        )
    )
    return max(
        0,
        cfg.context_tokens
        - cfg.llm.max_tokens
        - len((TRIAGE_SYSTEM + envelope).encode())
        - 128,
    )


def profile_key(cfg):
    from .analysis import TRIAGE_SYSTEM
    from .compaction import VERSION

    return hashlib.sha256(
        dumps(
            [
                cfg.llm.provider,
                cfg.llm.base_url.rstrip("/"),
                cfg.llm.model,
                cfg.context_tokens,
                cfg.llm.max_tokens,
                cfg.triage_thinking,
                cfg.sensitivity,
                TRIAGE_SYSTEM,
                VERSION,
            ]
        ).encode()
    ).hexdigest()[:20]


def batch_budget(store, cfg, ceiling):
    maximum = max(0, min(cfg.input_budget, ceiling))
    initial = min(maximum, 5000)
    samples = []
    with store.connect() as db:
        rows = db.execute(
            "SELECT duration,status,input_tokens,output_tokens,detail FROM usage "
            "WHERE kind='analysis' ORDER BY created DESC LIMIT 100"
        ).fetchall()
    for row in rows:
        detail = json.loads(row["detail"])
        if detail.get("review_profile") == profile_key(cfg):
            sample = dict(row, detail=detail)
            load = detail.get("load_seconds", 0)
            sample["work_seconds"] = (
                row["duration"] - load
                if type(load) in (int, float) and 0 <= load <= row["duration"]
                else row["duration"]
            )
            samples.append(sample)
        if len(samples) == 8:
            break
    chosen, reason = initial, "warming_up"
    if not cfg.adaptive_batching:
        chosen, reason = maximum, "fixed_limit"
    elif samples:
        latest = samples[0]
        previous = latest["detail"].get("batch_budget_bytes", initial)
        previous = min(maximum, max(min(512, maximum), previous))
        if latest["status"] != "ok":
            chosen, reason = (
                max(min(512, maximum), int(previous * 0.65)),
                "recent_error",
            )
        elif latest["work_seconds"] > cfg.target_batch_seconds * 1.3:
            chosen, reason = max(min(1024, maximum), int(previous * 0.75)), "slow_batch"
        elif len(samples) >= 3 and all(r["status"] == "ok" for r in samples[:3]):
            seconds = median(r["work_seconds"] for r in samples[:3])
            if seconds < cfg.target_batch_seconds * 0.8:
                chosen, reason = min(maximum, int(previous * 1.25)), "spare_time"
            else:
                chosen, reason = previous, "within_target"
        else:
            chosen = previous
    return dict(
        review_profile=profile_key(cfg),
        input_bytes=max(0, min(chosen, maximum)),
        maximum_bytes=maximum,
        samples=len(samples),
        reason=reason,
        target_seconds=cfg.target_batch_seconds,
        median_seconds=median(r["duration"] for r in samples) if samples else None,
        median_work_seconds=(
            median(r["work_seconds"] for r in samples) if samples else None
        ),
        input_tokens_median=(
            median(r["input_tokens"] for r in samples if r["input_tokens"] is not None)
            if any(r["input_tokens"] is not None for r in samples)
            else None
        ),
        output_tokens_median=(
            median(
                r["output_tokens"] for r in samples if r["output_tokens"] is not None
            )
            if any(r["output_tokens"] is not None for r in samples)
            else None
        ),
    )
