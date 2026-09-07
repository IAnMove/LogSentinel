"""Durable log sender with independent capture, heartbeat and retrying delivery."""

import json
import time
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from .collect import Collector
from .models import Source, check_url
from .store import Store
from .sender import blocking, run_workers, spool_lock, status


async def forward(path, receiver, source_id, token, directory, once=False):
    check_url(receiver)
    if urlsplit(receiver).scheme != "https" and urlsplit(receiver).hostname not in (
        "localhost",
        "127.0.0.1",
        "::1",
    ):
        raise ValueError("Use HTTPS or a loopback SSH tunnel")
    store = Store(directory)
    # Bind relative CLI paths to this working directory on first use. Upgrades of
    # legacy relative-path spools must run from their original working directory.
    path = str(Path(path).expanduser().absolute())
    existing = store.get("source", "sender")
    if existing and str(Path(existing["path"]).expanduser().absolute()) != path:
        raise ValueError("This spool belongs to another path")
    with spool_lock(store, ["logs", receiver.rstrip("/"), source_id, path]):
        collector = Collector(store)
        source = store.get("source", "sender")
        if source is None:
            model = Source(
                name="Forwarded file",
                machine_id="sender",
                path=path,
                enabled=True,
                history=True,
            )
            store.put("source", model.model_dump(), "sender")
            source = store.get("source", "sender")
        elif source["path"] != path:
            source["path"] = path
            store.put(
                "source", {k: v for k, v in source.items() if k != "id"}, "sender"
            )
        heartbeat_due = 0
        headers = {"Authorization": "Bearer " + token}
        try:
            async with httpx.AsyncClient(
                timeout=20, trust_env=False, follow_redirects=False
            ) as client:

                async def capture():
                    await blocking(collector.poll, source)
                    health = json.loads(store.meta("health:sender") or "{}")
                    if health.get("status") == "error":
                        raise OSError("Collector reported an error")

                async def deliver():
                    nonlocal heartbeat_due
                    rows = store.events(source_id="sender", status="pending", limit=100)
                    payload, size = {"events": []}, 0
                    for event in rows:
                        item = {
                            "id": event["id"],
                            "raw": event.get("raw", event["message"]),
                        }
                        cost = len(json.dumps(item).encode())
                        if size + cost > 3_000_000:
                            break
                        payload["events"].append(item)
                        size += cost
                    try:
                        if payload["events"]:
                            response = await client.post(
                                receiver.rstrip("/") + "/ingest/" + source_id,
                                headers=headers,
                                json=payload,
                            )
                            response.raise_for_status()
                            result = response.json()
                            ids = [e["id"] for e in payload["events"]]
                            if result.get("status") != "durable" or set(
                                result.get("acknowledged", [])
                            ) != set(ids):
                                raise ValueError("Incomplete acknowledgment")
                            store.mark(ids, "sent")
                            await blocking(store.discard_sent)
                        if time.monotonic() >= heartbeat_due:
                            capture_state = json.loads(
                                store.meta("sender_capture") or "{}"
                            )
                            with store.connect() as db:
                                pending = db.execute(
                                    "SELECT count(*) FROM events WHERE status='pending'"
                                ).fetchone()[0]
                            response = await client.post(
                                receiver.rstrip("/") + "/heartbeat/" + source_id,
                                headers=headers,
                                json={
                                    "ok": capture_state.get("ok", False),
                                    "pending": pending,
                                },
                            )
                            if response.status_code != 404:
                                response.raise_for_status()
                            heartbeat_due = time.monotonic() + 30
                        status(store, "delivery", True)
                        return True
                    except (httpx.HTTPError, ValueError, TypeError):
                        status(
                            store,
                            "delivery",
                            False,
                            "Delivery failed; durable spool retained; retrying with backoff",
                        )
                        if once:
                            raise RuntimeError(
                                "Forwarding failed; spool retained for retry"
                            ) from None
                        return False

                await run_workers(capture, deliver, 2, store, once)
        finally:
            collector.close()
