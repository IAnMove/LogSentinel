"""Empirical model latency estimates; estimates are never completion guarantees."""

import hashlib
import json
from statistics import median


def endpoint_id(cfg):
    return hashlib.sha256(cfg.llm.base_url.rstrip("/").encode()).hexdigest()[:16]


def estimate_model_time(store, kind="chat"):
    cfg = store.settings()
    with store.connect() as db:
        rows = db.execute(
            "SELECT kind,duration,status,detail FROM usage ORDER BY created DESC LIMIT 200"
        ).fetchall()
    matches = []
    for row in rows:
        detail = json.loads(row["detail"])
        if (
            detail.get("model") == cfg.llm.model
            and detail.get("provider") == cfg.llm.provider
            and detail.get("endpoint_id", endpoint_id(cfg)) == endpoint_id(cfg)
            and row["status"] == "ok"
            and row["duration"] > 0
        ):
            matches.append(row)
    specific = [r for r in matches if r["kind"] == kind]
    chosen = (specific if len(specific) >= 3 else matches)[:12]
    return dict(
        expected_seconds=(
            round(median(r["duration"] for r in chosen)) if chosen else None
        ),
        samples=len(chosen),
        basis="same_task" if len(specific) >= 3 else "same_model",
        model=cfg.llm.model,
        timeout_seconds=cfg.llm.timeout_seconds,
    )
