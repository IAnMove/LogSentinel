"""Durable metrics sender; slow delivery never stalls scheduled sampling."""

import json
from urllib.parse import urlsplit
import httpx
from .models import check_url
from .store import Store, dumps
from .telemetry_data import LinuxSampler, TelemetryConfig
from .sender import blocking, run_workers, spool_lock, status


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
    with spool_lock(store, ["metrics", receiver.rstrip("/"), machine]):
        store.set_meta("telemetry_receiver", binding)
        source = {"id": "metric-sender", "machine_id": machine}
        sampler = LinuxSampler()
        async with httpx.AsyncClient(
            timeout=20, trust_env=False, follow_redirects=False
        ) as client:

            async def capture():
                sample = await blocking(sampler.sample, config.disk_paths)
                await blocking(
                    store.ingest,
                    source,
                    [{"origin": sample.id, "message": dumps(sample.model_dump())}],
                )

            async def deliver():
                rows = store.events(source_id=source["id"], status="pending", limit=20)
                if not rows:
                    return True
                samples = [json.loads(row["message"]) for row in rows]
                try:
                    response = await client.post(
                        receiver.rstrip("/") + "/ingest-metrics/" + machine,
                        json={"samples": samples},
                        headers={"Authorization": "Bearer " + token},
                    )
                    response.raise_for_status()
                    ack = response.json()
                    accepted = set(ack.get("acknowledged", []))
                    rejected = ack.get("rejected", [])
                    quarantined = {
                        r["id"] for r in rejected if r.get("reason") == "expired"
                    }
                    if (
                        ack.get("status") != "durable"
                        or accepted & quarantined
                        or accepted | quarantined != {s["id"] for s in samples}
                        or len(quarantined) != len(rejected)
                    ):
                        raise ValueError("Incomplete acknowledgment")
                    store.mark(
                        [
                            r["id"]
                            for r in rows
                            if json.loads(r["message"])["id"] in accepted
                        ],
                        "sent",
                    )
                    store.mark(
                        [
                            r["id"]
                            for r in rows
                            if json.loads(r["message"])["id"] in quarantined
                        ],
                        "quarantined",
                    )
                    if quarantined:
                        store.audit(
                            "sender_quarantine",
                            dumps(dict(reason="expired", ids=sorted(quarantined))),
                        )
                        status(
                            store,
                            "quarantine",
                            False,
                            "Expired measurements retained in local quarantine; inspect spool-status",
                        )
                    await blocking(store.discard_sent)
                    status(store, "delivery", True)
                    return True
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    status(
                        store,
                        "delivery",
                        False,
                        "Metrics delivery failed; durable spool retained; retrying with backoff",
                    )
                    if once:
                        raise RuntimeError(
                            "Metrics forwarding failed; spool retained for retry"
                        ) from None
                    return False

            await run_workers(capture, deliver, interval, store, once)
