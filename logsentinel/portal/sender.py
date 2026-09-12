"""Shared sender supervision; durable queues are never discarded on failure."""

import asyncio
from contextlib import contextmanager
import fcntl
import json
import logging
import time
from .store import dumps

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


def status(store, worker, ok, message=""):
    old = json.loads(store.meta("sender_" + worker) or "{}")
    store.set_meta(
        "sender_" + worker, dumps(dict(ok=ok, checked=time.time(), message=message))
    )
    if old.get("ok") != ok or old.get("message") != message:
        log.warning("Sender %s: %s", worker, message or "recovered")


async def blocking(fn, *args):
    """Finish the last blocking read before closing its collector on cancellation."""
    task = asyncio.create_task(asyncio.to_thread(fn, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


async def run_workers(capture, deliver, interval, store, once):
    async def collect_once():
        try:
            await capture()
            status(store, "capture", True)
        except (OSError, ValueError):
            status(
                store,
                "capture",
                False,
                "Capture failed; inspect source permissions and spool space",
            )
            if once:
                raise

    async def capture_loop():
        while True:
            started = time.monotonic()
            await collect_once()
            await asyncio.sleep(max(0.1, interval - (time.monotonic() - started)))

    async def delivery_loop():
        delay = 2
        while True:
            result = await deliver()
            if type(result) is int:
                # The receiver stated how long its quota needs; waiting less only
                # spends the sender's own retries against a refusal it can predict.
                # A stated pause is not a transport failure, so backoff stays reset.
                pause, delay = max(1, min(3600, result)), 2
            else:
                delay = 2 if result else min(60, delay * 2)
                pause = delay
            await asyncio.sleep(pause)

    if once:
        await collect_once()
        await deliver()
        return
    tasks = [asyncio.create_task(capture_loop()), asyncio.create_task(delivery_loop())]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
