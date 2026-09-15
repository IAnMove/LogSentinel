"""Authenticated control independent of log delivery, including while paused."""

import asyncio
import time
import sqlite3
import httpx

from logsentinel import __version__
from .sender import blocking, status
from .sender_safety import SenderWait, error_detail, io_pressure


class SenderControl:
    def __init__(self, store, client, receiver, source_id, headers):
        self.store, self.client = store, client
        self.base, self.source, self.headers = receiver.rstrip("/"), source_id, headers
        self.capture_allowed = self.delivery_allowed = False
        self.state, self.lease_until = "control_unavailable", 0

    def require(self, capture=False):
        allowed = self.capture_allowed if capture else self.delivery_allowed
        if not allowed or time.monotonic() >= self.lease_until:
            raise SenderWait(self.state if not allowed else "control_unavailable")

    async def refresh(self):
        try:
            response = await self.client.get(
                self.base + "/sender-control/" + self.source, headers=self.headers
            )
            legacy = response.status_code == 404
            if not legacy:
                response.raise_for_status()
                value = response.json()
                if (
                    not isinstance(value, dict)
                    or value.get("version") != 1
                    or any(
                        type(value.get(k)) is not bool
                        for k in ("capture_allowed", "delivery_allowed")
                    )
                    or value.get("state")
                    not in ("active", "machine_paused", "source_disabled")
                ):
                    raise ValueError("Invalid sender control response")
                self.capture_allowed, self.delivery_allowed = (
                    value["capture_allowed"],
                    value["delivery_allowed"],
                )
                self.state, self.lease_until = value["state"], time.monotonic() + 90
            cache = getattr(self.store, "_sender_status", {})
            capture = cache.get("capture", {})
            capture_stalled = (
                capture.get("ok", False)
                and time.time() - capture.get("checked", 0) > 90
            )
            payload = dict(
                ok=capture.get("ok", False) and not capture_stalled,
                pending=await blocking(self.store.sender_pending),
            )
            if not legacy:
                storage = await blocking(self.store.storage_usage)
                payload.update(
                    {
                        k: storage[k]
                        for k in (
                            "allocated_bytes",
                            "used_bytes",
                            "quota_bytes",
                            "disk_free_bytes",
                        )
                    }
                )
                payload.update(
                    capture_code=(
                        "capture_stalled"
                        if capture_stalled
                        else capture.get("code", "")
                    ),
                    delivery_code=cache.get("delivery", {}).get("code", ""),
                    build=__version__,
                    io_pressure_percent=io_pressure(),
                )
            response = await self.client.post(
                self.base + "/heartbeat/" + self.source,
                headers=self.headers,
                json=payload,
            )
            response.raise_for_status()
            heartbeat = response.json()
            if not isinstance(heartbeat, dict) or heartbeat.get("ok") is not True:
                raise ValueError("Invalid heartbeat acknowledgement")
            if legacy:
                # Older receivers reject paused heartbeat requests. A success is
                # their explicit acknowledgement that this source can send again.
                self.capture_allowed = self.delivery_allowed = True
                self.state, self.lease_until = "active", time.monotonic() + 90
            await blocking(status, self.store, "control", True, self.state)
        except (httpx.HTTPError, ValueError, TypeError, sqlite3.Error, OSError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (
                401,
                403,
                409,
            ):
                self.capture_allowed = self.delivery_allowed = False
                self.state = error_detail(exc)["code"]
            await asyncio.to_thread(
                status,
                self.store,
                "control",
                False,
                "Control unavailable; capture lease is bounded",
                **error_detail(exc),
                next_retry=time.time() + 30,
            )
