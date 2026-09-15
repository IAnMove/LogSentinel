"""Durable log sender with independent capture, heartbeat and retrying delivery."""

import json
import asyncio
import time
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from .network import CheckedAsyncTransport
from .collect import Collector
from .models import Source, check_url
from .store import Store
from .sender import blocking, run_workers, spool_lock, status
from .sender_safety import SenderLimits, CaptureGate, error_detail
from .sender_control import SenderControl


async def forward(
    path,
    receiver,
    source_id,
    token,
    directory,
    once=False,
    *,
    journal=False,
    new_only=False,
    limits=None,
):
    check_url(receiver)
    if urlsplit(receiver).scheme != "https" and urlsplit(receiver).hostname not in (
        "localhost",
        "127.0.0.1",
        "::1",
    ):
        raise ValueError("Use HTTPS or a loopback SSH tunnel")
    if bool(path) == bool(journal):
        raise ValueError("Select one file path or --journal")
    store = Store(directory)
    # Bind relative CLI paths to this working directory on first use. Upgrades of
    # legacy relative-path spools must run from their original working directory.
    path = "" if journal else str(Path(path).expanduser().absolute())
    existing = store.get("source", "sender")
    kind = "journald" if journal else "file"
    if existing and (
        existing["kind"] != kind
        or (not journal and str(Path(existing["path"]).expanduser().absolute()) != path)
    ):
        raise ValueError("This spool belongs to another path")
    identity = (
        ["journal", receiver.rstrip("/"), source_id]
        if journal
        else ["logs", receiver.rstrip("/"), source_id, path]
    )
    with spool_lock(store, identity):
        await blocking(store.prepare_sender)
        limits = SenderLimits.model_validate(limits or {})
        gate = CaptureGate(store, limits)
        collector = Collector(store)
        source = store.get("source", "sender")
        if source is None:
            model = Source(
                name="Forwarded journal" if journal else "Forwarded file",
                machine_id="sender",
                kind=kind,
                path=path,
                enabled=True,
                history=not new_only,
            )
            store.put("source", model.model_dump(), "sender")
            source = store.get("source", "sender")
        elif source["path"] != path:
            source["path"] = path
            store.put(
                "source", {k: v for k, v in source.items() if k != "id"}, "sender"
            )
        source = dict(
            source,
            max_batch_bytes=min(source["max_batch_bytes"], limits.capture_batch_bytes),
        )
        journal_supported = False
        cleanup_due = 0
        headers = {"Authorization": "Bearer " + token}
        ca_path = store.directory / "receiver-ca.pem"
        verify = str(ca_path) if ca_path.exists() else True
        try:
            async with httpx.AsyncClient(
                transport=CheckedAsyncTransport(verify=verify),
                timeout=20,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                control = SenderControl(store, client, receiver, source_id, headers)

                async def capture():
                    control.require(capture=True)
                    await blocking(gate.check)
                    await blocking(collector.poll, source, True)

                async def deliver():
                    nonlocal journal_supported, cleanup_due
                    control.require()
                    await asyncio.to_thread(gate.check, delivery=True)
                    if time.monotonic() >= cleanup_due:
                        # Recover acknowledgements committed just before a crash.
                        await blocking(store.discard_sent)
                        cleanup_due = time.monotonic() + 3600
                    rows = await asyncio.to_thread(
                        store.events, source_id="sender", status="pending", limit=100
                    )
                    payload, size = {"events": []}, 0
                    if journal:
                        payload["format"] = "journal"
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
                        if journal and not journal_supported:
                            capabilities = await client.get(
                                receiver.rstrip("/") + "/ingest-info"
                            )
                            capabilities.raise_for_status()
                            info = capabilities.json()
                            if (
                                not isinstance(info, dict)
                                or not isinstance(info.get("formats"), list)
                                or "journal" not in info["formats"]
                            ):
                                raise ValueError(
                                    "The receiver needs journal ingestion support"
                                )
                            journal_supported = True
                        if payload["events"]:
                            response = await client.post(
                                receiver.rstrip("/") + "/ingest/" + source_id,
                                headers=headers,
                                json=payload,
                            )
                            response.raise_for_status()
                            result = response.json()
                            ids = [e["id"] for e in payload["events"]]
                            if (
                                not isinstance(result, dict)
                                or result.get("status") != "durable"
                                or set(result.get("acknowledged", [])) != set(ids)
                            ):
                                raise ValueError("Incomplete acknowledgment")
                            await blocking(store.mark, ids, "sent")
                            await blocking(store.discard_sent, ids)
                        await blocking(status, store, "delivery", True)
                        return True
                    except (httpx.HTTPError, ValueError, TypeError) as failure:
                        # A quota refusal states how long to wait, so honour it
                        # instead of spending retries on a predictable rejection.
                        wait = 0
                        if (
                            isinstance(failure, httpx.HTTPStatusError)
                            and failure.response.status_code == 429
                        ):
                            header = failure.response.headers.get("retry-after", "")
                            wait = min(3600, int(header) if header.isdigit() else 60)
                        if isinstance(
                            failure, httpx.HTTPStatusError
                        ) and failure.response.status_code in (401, 403, 409):
                            control.capture_allowed = control.delivery_allowed = False
                            control.state = error_detail(failure)["code"]
                        await asyncio.to_thread(
                            status,
                            store,
                            "delivery",
                            False,
                            "Delivery failed; durable spool retained",
                            **error_detail(failure),
                            next_retry=time.time() + (wait or 60),
                        )
                        if once:
                            raise RuntimeError(
                                "Forwarding failed; spool retained for retry"
                            ) from None
                        return wait or False

                await run_workers(
                    capture, deliver, 2, store, once, control=control.refresh
                )
        finally:
            collector.close()
