"""Background loops: capture, analysis, detection, delivery, metrics and supervision."""

from __future__ import annotations

import asyncio
import time

from ..analysis import safe_error
from ..rules import (
    redact,
)


def build_workers(ctx):
    (
        store,
        collector,
        analyzer,
        monitor,
        researcher,
        telemetry,
        outbox,
        health_monitor,
    ) = (
        ctx.store,
        ctx.collector,
        ctx.analyzer,
        ctx.monitor,
        ctx.researcher,
        ctx.telemetry,
        ctx.outbox,
        ctx.health_monitor,
    )

    async def collecting():
        while True:
            failed = False
            for source in store.objects("source"):
                try:
                    await asyncio.to_thread(collector.poll, source)
                except Exception:
                    failed = True
                    store.set_meta("collector_error", "Collector worker failed")
            monitor.capture_heartbeat = time.time()
            health_monitor.beat("capture")
            if not failed:
                store.set_meta("collector_error", "")
            await asyncio.sleep(2)

    async def working():
        last_prune = 0
        while True:
            try:
                await monitor.tick()
                await researcher.tick()
                await telemetry.analyze_tick()
                if time.time() - last_prune > 3600:
                    await asyncio.to_thread(store.prune)
                    last_prune = time.time()
                store.set_meta("worker_error", "")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                store.set_meta("worker_error", redact(str(exc))[:200])
            health_monitor.beat("analysis")
            await asyncio.sleep(1)

    async def detecting():
        from ..signal_scan import scan_signals

        while True:
            try:
                if store.settings().enabled:
                    await asyncio.to_thread(scan_signals, analyzer)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                store.set_meta("detector_worker_error", safe_error(exc))
            await asyncio.sleep(1)

    async def delivering():
        while True:
            try:
                await outbox.drain()
                store.set_meta("delivery_worker_error", "")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                store.set_meta(
                    "delivery_worker_error",
                    safe_error(exc, (store.settings().llm.api_key,)),
                )
            health_monitor.beat("notifications")
            await asyncio.sleep(2)

    async def measuring():
        while True:
            try:
                await asyncio.to_thread(telemetry.tick)
                store.set_meta("telemetry_worker_error", "")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                store.set_meta("telemetry_worker_error", safe_error(exc))
            health_monitor.beat("metrics")
            await asyncio.sleep(2)

    async def supervising():
        while True:
            try:
                await asyncio.to_thread(health_monitor.tick)
                store.set_meta("health_worker_error", "")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                store.set_meta("health_worker_error", safe_error(exc))
            await asyncio.sleep(5)

    return collecting, working, detecting, delivering, measuring, supervising
