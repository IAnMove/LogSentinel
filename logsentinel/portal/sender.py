"""Shared sender supervision; durable queues are never discarded on failure."""

import asyncio
from contextlib import contextmanager
import fcntl
import json
import logging
import sqlite3
import time
from .store import dumps
from .sender_safety import SenderWait, error_detail

log = logging.getLogger(__name__)


@contextmanager
def spool_lock(store, identity):
    with (store.directory / "sender.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("Another sender is using this spool") from None
        binding = dumps(identity)
        if store.meta("sender_binding") not in (None, binding):
            raise ValueError("This spool belongs to another receiver, source or path")
        store.set_meta("sender_binding", binding)
        yield


def status(store, worker, ok, message="", **detail):
    cache = getattr(store, "_sender_status", None)
    if cache is None:
        cache = store._sender_status = {}
    now = time.time()
    old = cache.get(worker, {})
    changed = (
        old.get("ok") != ok
        or old.get("message") != message
        or old.get("code") != detail.get("code")
    )
    if not changed and now - old.get("checked", 0) < 30:
        return
    value = dict(
        ok=ok,
        checked=now,
        phase=worker,
        message=message,
        last_success=now if ok else old.get("last_success"),
        **detail,
    )
    cache[worker] = value
    if changed:
        log.warning("Sender %s: %s", worker, dumps(value))
    try:
        store.set_meta("sender_" + worker, dumps(value))
    except (sqlite3.Error, OSError) as exc:
        # A failed diagnostic write must not restart the service in a tight loop.
        log.error("Sender status persistence: %s", dumps(error_detail(exc)))


async def blocking(fn, *args):
    """Finish the last blocking read before closing its collector on cancellation."""
    task = asyncio.create_task(asyncio.to_thread(fn, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


async def run_workers(capture, deliver, interval, store, once, control=None):
    failures = 0

    async def collect_once():
        nonlocal failures
        try:
            await capture()
            failures = 0
            await blocking(status, store, "capture", True)
            return interval
        except (OSError, ValueError, sqlite3.Error, SenderWait) as exc:
            failures = min(5, failures + 1)
            delay = (
                exc.seconds
                if isinstance(exc, SenderWait)
                else min(300, 30 * 2 ** (failures - 1))
            )
            await asyncio.to_thread(
                status,
                store,
                "capture",
                False,
                "Capture suspended; durable cursor retained",
                **error_detail(exc),
                next_retry=time.time() + delay,
            )
            if once and not isinstance(exc, SenderWait):
                raise
            return delay

    async def capture_loop():
        while True:
            started = time.monotonic()
            delay = await collect_once()
            elapsed = time.monotonic() - started
            # Failed/slow storage gets rest after the operation, not an immediate
            # retry just because the operation already consumed the interval.
            pause = delay if failures else max(delay - elapsed, min(300, elapsed))
            await asyncio.sleep(max(0.1, pause))

    async def delivery_loop():
        delay = 2
        while True:
            started = time.monotonic()
            try:
                result = await deliver()
            except (OSError, sqlite3.Error, SenderWait) as exc:
                result = exc.seconds if isinstance(exc, SenderWait) else 60
                await asyncio.to_thread(
                    status,
                    store,
                    "delivery",
                    False,
                    "Delivery suspended; durable spool retained",
                    **error_detail(exc),
                    next_retry=time.time() + result,
                )
            if type(result) is int:
                # The receiver stated how long its quota needs; waiting less only
                # spends the sender's own retries against a refusal it can predict.
                # A stated pause is not a transport failure, so backoff stays reset.
                pause, delay = max(1, min(3600, result)), 2
            else:
                delay = 2 if result else min(60, delay * 2)
                pause = delay
            # Slow storage lowers throughput instead of an immediate catch-up burst.
            await asyncio.sleep(max(pause, min(300, time.monotonic() - started)))

    async def control_loop():
        while True:
            await asyncio.sleep(30)
            await control()

    if control:
        await control()

    if once:
        await collect_once()
        try:
            await deliver()
        except SenderWait as exc:
            await asyncio.to_thread(
                status,
                store,
                "delivery",
                False,
                "Delivery paused; durable spool retained",
                **error_detail(exc),
            )
            if exc.code in (
                "control_unavailable",
                "authentication_failed",
                "forbidden",
                "connection_failed",
                "tls_failed",
            ):
                raise RuntimeError(
                    "Forwarding failed; spool retained for retry"
                ) from None
        finally:
            if control:
                await control()
        return
    tasks = [asyncio.create_task(capture_loop()), asyncio.create_task(delivery_loop())]
    if control:
        tasks.append(asyncio.create_task(control_loop()))
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
