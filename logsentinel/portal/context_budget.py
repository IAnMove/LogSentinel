"""Measured token estimates, used only with a backend that rejects truncation."""

import json
import math
import re
import time

import httpx

from .store import dumps


def backend_key(cfg):
    from .model_timing import endpoint_id
    return "context_backend:" + endpoint_id(cfg)


def token_samples(store, cfg):
    from .batch_budget import profile_key
    profile = profile_key(cfg)
    ratios = []
    with store.connect() as db:
        rows = db.execute("SELECT input_tokens,detail FROM usage WHERE kind='analysis' AND status='ok' AND input_tokens>0 ORDER BY created DESC LIMIT 100").fetchall()
    for row in rows:
        detail = json.loads(row["detail"])
        size = detail.get("total_input_bytes", 0)
        if detail.get("review_profile") == profile and type(size) is int and size > 0:
            ratios.append(row["input_tokens"] / size)
    return ratios[:12]


def token_policy(store, cfg):
    samples = token_samples(store, cfg)
    backend = json.loads(store.meta(backend_key(cfg)) or "{}")
    from .batch_budget import profile_key
    blocked = float(store.meta("context_conservative:" + profile_key(cfg)) or 0) > time.time()
    safe = not blocked and cfg.llm.provider == "ollama" and backend.get("rejects_truncation") and time.time() - backend.get("checked", 0) < 300
    ratio = max(0.35, min(1.0, max(samples) * 1.25)) if safe and len(samples) >= 3 else 1.0
    return dict(tokens_per_byte=ratio, samples=len(samples), method="measured_with_rejection" if ratio < 1 else "utf8_upper_bound", backend_version=backend.get("version"))


async def check_backend(client, store, cfg, headers):
    if cfg.llm.provider != "ollama":
        return
    safe, version = False, None
    try:
        response = await client.get(cfg.llm.base_url.rstrip("/") + "/api/version", headers=headers, timeout=5)
        response.raise_for_status()
        version = response.json().get("version", "")
        match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
        # This release's ChatRequest defines both truncate and shift. Older or
        # unidentified servers keep the byte bound rather than silently clipping.
        safe = bool(match and tuple(map(int, match.groups())) >= (0, 33, 2))
    except (httpx.HTTPError, ValueError, AttributeError, TypeError):
        pass
    store.set_meta(backend_key(cfg), dumps(dict(checked=time.time(), version=version, rejects_truncation=safe)))


def input_bytes(store, cfg):
    ratio = token_policy(store, cfg)["tokens_per_byte"] if store is not None else 1.0
    return max(0, math.floor((cfg.context_tokens - cfg.llm.max_tokens - 256) / ratio))


def context_rejection(response):
    if response.status_code not in (400, 413, 422):
        return False
    # Never store or display this remote body. Only recognise bounded error codes.
    message = response.text[:4000].lower()
    return any(marker in message for marker in (
        "exceed_context_size_error", "context_length_exceeded", "exceeds the context length",
        "exceeds the available context", "maximum context length",
    ))
