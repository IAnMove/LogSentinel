"""Durable sender of a machine's inventory and activity to the central.

Same shape as the metrics sender: records are written to a local spool first
and deleted only after the central confirms it stored them, so a central that
is down, or a tunnel that drops, loses nothing.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from . import brain_collect
from .models import check_url
from .network import CheckedAsyncTransport, private_authority
from .sender import blocking, run_workers, spool_lock, status
from .store import Store, dumps

BATCH = 200
# Refused for a reason that waiting will not change; kept out of the queue.
FINAL_REFUSALS = ("expired", "future", "activity_disabled")


async def forward_brain(
    receiver,
    machine,
    token,
    directory,
    inventory_interval=86400,
    activity=True,
    activity_interval=60,
    once=False,
):
    check_url(receiver)
    url = urlsplit(receiver)
    if url.scheme != "https" and url.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("Use HTTPS or a loopback SSH tunnel")
    store = Store(directory)
    with spool_lock(store, ["brain", receiver.rstrip("/"), machine]):
        source = {"id": "brain-sender", "machine_id": machine}
        ca_path = Path(directory) / "receiver-ca.pem"
        verify = private_authority(ca_path) if ca_path.is_file() else True
        async with httpx.AsyncClient(
            transport=CheckedAsyncTransport(verify=verify),
            timeout=60,
            trust_env=False,
            follow_redirects=False,
        ) as client:

            def spool(records):
                if records:
                    store.ingest(
                        source,
                        [{"origin": r["id"], "message": dumps(r)} for r in records],
                    )

            def capture_blocking():
                now = time.time()
                if now - float(store.meta("brain_inventory_at") or 0) >= inventory_interval:
                    spool([brain_collect.inventory(now)])
                    store.set_meta("brain_inventory_at", str(now))
                if activity:
                    records, cursor = brain_collect.read_activity(
                        store.meta("brain_cursor") or ""
                    )
                    spool(records)
                    if cursor:
                        store.set_meta("brain_cursor", cursor)

            async def capture():
                await blocking(capture_blocking)

            async def deliver():
                rows = store.events(source_id=source["id"], status="pending", limit=BATCH)
                if not rows:
                    return True
                items = [json.loads(row["message"]) for row in rows]
                try:
                    response = await client.post(
                        receiver.rstrip("/") + "/ingest-brain/" + machine,
                        json={"items": items},
                        headers={"Authorization": "Bearer " + token},
                    )
                    if response.status_code == 429:
                        return int(response.headers.get("retry-after", "60"))
                    response.raise_for_status()
                    ack = response.json()
                    if ack.get("status") != "durable":
                        raise ValueError("Incomplete acknowledgment")
                    settled = set(ack.get("acknowledged", [])) | {
                        r["id"] for r in ack.get("rejected", []) if r.get("reason") in FINAL_REFUSALS
                    }
                    store.mark(
                        [r["id"] for r in rows if json.loads(r["message"])["id"] in settled],
                        "sent",
                    )
                    await blocking(store.discard_sent)
                    status(store, "delivery", True)
                    return "more" if len(rows) == BATCH else True
                except (httpx.HTTPError, ValueError, KeyError, TypeError):
                    status(
                        store,
                        "delivery",
                        False,
                        "Brain delivery failed; durable spool retained; retrying with backoff",
                    )
                    if once:
                        raise RuntimeError(
                            "Brain forwarding failed; spool retained for retry"
                        ) from None
                    return False

            await run_workers(capture, deliver, activity_interval, store, once)
