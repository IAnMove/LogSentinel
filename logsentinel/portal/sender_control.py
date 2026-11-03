"""Authenticated control independent of log delivery, including while paused."""

import asyncio
import json
import os
import re
import tempfile
import time
import sqlite3
import httpx

from logsentinel import __version__
from .sender import blocking, status
from .sender_safety import SenderWait, error_detail, io_pressure


COMMIT = re.compile(r"^[0-9a-f]{40}$")
VERSION = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")
# The file this unprivileged process leaves for the root job that may act on
# it; the job treats it as untrusted input and only ever reads the commit.
REQUEST_FILE = "upgrade-request.json"


class UpgradeChannel:
    """What the sender knows about remote upgrades, without the power to do one.

    The central offers a commit; this process can only write it down in its
    own spool. Whether anything happens next is decided by root on this host:
    the policy flag is in root's configuration, and the result file is root's.
    """

    def __init__(self, store, enabled=False, state_path=None):
        self.store, self.enabled = store, bool(enabled)
        self.state_path = state_path
        self.offered = None

    def accept(self, offer):
        """Validate the central's offer; anything malformed counts as no offer."""
        if (
            isinstance(offer, dict)
            and isinstance(offer.get("commit"), str)
            and COMMIT.match(offer["commit"])
            and isinstance(offer.get("version"), str)
            and VERSION.match(offer["version"])
        ):
            self.offered = dict(version=offer["version"], commit=offer["commit"])
        else:
            self.offered = None
        path = self.store.directory / REQUEST_FILE
        if self.offered is None or not self.enabled:
            path.unlink(missing_ok=True)
            return
        wanted = json.dumps(dict(self.offered, seen=int(time.time())))
        try:
            if json.loads(path.read_text()).get("commit") == self.offered["commit"]:
                return
        except (OSError, ValueError, AttributeError):
            pass
        fd, temp = tempfile.mkstemp(prefix=".upgrade-", dir=self.store.directory)
        with os.fdopen(fd, "w") as handle:
            handle.write(wanted)
        os.replace(temp, path)

    def report(self):
        """The heartbeat field: policy, what was offered and root's last result."""
        result = dict(
            policy="enabled" if self.enabled else "disabled",
            offered=self.offered["commit"] if self.offered else "",
        )
        try:
            state = json.loads(self.state_path.read_text()) if self.state_path else {}
        except (OSError, ValueError):
            state = {}
        if not isinstance(state, dict):
            state = {}
        for key, pattern in (
            ("status", r"^[a-z_]{1,40}$"),
            ("commit", r"^[0-9a-f]{40}$"),
            ("version", r"^[A-Za-z0-9_.-]{1,80}$"),
        ):
            value = state.get(key)
            if isinstance(value, str) and re.match(pattern, value):
                result[key] = value
        if isinstance(state.get("observed"), (int, float)) and 0 <= state["observed"] < 10**12:
            result["observed"] = float(state["observed"])
        if isinstance(state.get("message"), str):
            result["message"] = "".join(
                c for c in state["message"] if c.isprintable()
            )[:300]
        return result


class SenderControl:
    def __init__(self, store, client, receiver, source_id, headers, upgrade=None):
        self.store, self.client = store, client
        self.base, self.source, self.headers = receiver.rstrip("/"), source_id, headers
        self.capture_allowed = self.delivery_allowed = False
        self.state, self.lease_until = "control_unavailable", 0
        self.upgrade = upgrade or UpgradeChannel(store)
        # Only a central that itself sends the upgrade key understands the
        # report; an older one refuses a heartbeat with a field it does not know.
        self.central_offers = False

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
                self.central_offers = "upgrade" in value
                if self.central_offers:
                    try:
                        self.upgrade.accept(value["upgrade"])
                    except OSError:
                        # A spool that cannot take the request file must not
                        # cost the heartbeat that keeps this sender authorised.
                        pass
            cache = getattr(self.store, "_sender_status", {})
            capture = cache.get("capture", {})
            capture_stalled = (
                capture.get("ok", False)
                and time.time() - capture.get("checked", 0) > 90
            )
            delivery = cache.get("delivery", {})
            # A delivery that has been failing for ten minutes is stuck, whatever
            # the capture is doing; the central used to see "ok" because only
            # the capture was asked. A fresh failure may still be an outage.
            delivery_blocked = not delivery.get("ok", True) and time.time() - (
                delivery.get("last_success") or delivery.get("checked") or time.time()
            ) > 600
            payload = dict(
                ok=capture.get("ok", False) and not capture_stalled and not delivery_blocked,
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
                    delivery_code="delivery_blocked" if delivery_blocked else delivery.get("code", ""),
                    rejected=await blocking(self.store.count_rejected),
                    build=__version__,
                    io_pressure_percent=io_pressure(),
                )
                if self.central_offers:
                    payload["upgrade"] = self.upgrade.report()
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
