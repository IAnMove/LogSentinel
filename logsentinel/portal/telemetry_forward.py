"""Durable telemetry sender over HTTPS or a loopback SSH tunnel."""

import asyncio
import fcntl
import json
import time
from urllib.parse import urlsplit

import httpx
from .models import check_url
from .store import Store, dumps
from .telemetry_data import LinuxSampler, TelemetryConfig


async def forward_metrics(
    receiver, machine, token, directory, interval=60, paths=None, once=False
):
    check_url(receiver)
    url = urlsplit(receiver)
    if url.scheme != "https" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Use HTTPS or a loopback SSH tunnel")
    config = TelemetryConfig(interval_seconds=interval, disk_paths=paths or ["/"])
    store = Store(directory)
    binding = dumps([receiver.rstrip("/"), machine])
    if store.meta("telemetry_receiver") not in (None, binding):
        raise ValueError("This spool belongs to another receiver or machine")
    lock = (store.directory / "metrics-sender.lock").open("a")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        store.set_meta("telemetry_receiver", binding)
        source = {"id": "metric-sender", "machine_id": machine}
        sampler = LinuxSampler()
        due = 0
        async with httpx.AsyncClient(
            timeout=20, trust_env=False, follow_redirects=False
        ) as client:
            while True:
                if time.monotonic() >= due:
                    sample = await asyncio.to_thread(sampler.sample, config.disk_paths)
                    store.ingest(
                        source,
                        [{"origin": sample.id, "message": dumps(sample.model_dump())}],
                    )
                    due = time.monotonic() + interval
                rows = store.events(source_id=source["id"], status="pending", limit=20)
                if rows:
                    samples = [json.loads(row["message"]) for row in rows]
                    try:
                        response = await client.post(
                            receiver.rstrip("/") + "/ingest-metrics/" + machine,
                            json={"samples": samples},
                            headers={"Authorization": "Bearer " + token},
                        )
                        response.raise_for_status()
                        ack = response.json()
                        if ack.get("status") != "durable" or set(
                            ack.get("acknowledged", [])
                        ) != {s["id"] for s in samples}:
                            raise ValueError("Incomplete acknowledgment")
                        store.mark([r["id"] for r in rows], "sent")
                        store.discard_sent()
                    except (httpx.HTTPError, ValueError):
                        if once:
                            raise RuntimeError(
                                "Metrics forwarding failed; spool retained for retry"
                            ) from None
                if once:
                    return
                await asyncio.sleep(min(2, max(0.1, due - time.monotonic())))
    finally:
        lock.close()
