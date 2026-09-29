"""Loopback portal API with session auth, CSRF checks and read-only chat tools.

create_app wires the parts together; the routes live in routes/, one module per
area, and the background loops in routes/workers.py.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .disk_info import register_disk_info
from .enroll import register_enrollment
from .ingest import register_ingest
from .machines import MachineLifecycle, register_machines
from .optimizer import register_optimizer
from .routes.access import register_access
from .routes.admin import register_admin
from .routes.chat import register_chat
from .routes.context import build_context
from .routes.model import register_model
from .routes.objects import register_objects
from .routes.problems import register_problems
from .routes.status import register_status
from .routes.web import register_web
from .routes.workers import build_workers
from .telemetry_api import register_telemetry
from .widget_api import register_widget


def create_app(directory, background=True):
    ctx = build_context(directory, background)
    store, collector, analyzer, monitor = (
        ctx.store,
        ctx.collector,
        ctx.analyzer,
        ctx.monitor,
    )
    researcher, telemetry, disk_scans = ctx.researcher, ctx.telemetry, ctx.disk_scans
    outbox, health_monitor = ctx.outbox, ctx.health_monitor
    collecting, working, detecting, delivering, measuring, supervising = build_workers(
        ctx
    )

    @asynccontextmanager
    async def lifespan(app):
        lockfile = (store.directory / "instance.lock").open("a")
        import fcntl

        try:
            fcntl.flock(lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lockfile.close()
            raise RuntimeError("Another portal is using this data directory") from None
        store.recover()
        researcher.recover()
        telemetry.recover()
        store.set_meta("model_active_call", "")
        disk_scans.recover()
        lifecycle.recover()
        chat_requests.recover()
        tasks = (
            [
                asyncio.create_task(f())
                for f in (
                    collecting,
                    working,
                    detecting,
                    delivering,
                    measuring,
                    supervising,
                )
            ]
            if background
            else []
        )
        try:
            yield
        finally:
            await lifecycle.close()
            await disk_scans.close()
            await chat_requests.close()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            collector.close()
            lockfile.close()

    app = FastAPI(
        title="LogSentinel",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.store = store
    app.state.analyzer = analyzer
    app.state.researcher = researcher
    app.state.telemetry = telemetry
    app.state.monitor = monitor
    app.state.outbox = outbox
    app.state.health = health_monitor
    app.state.sessions = ctx.sessions
    register_telemetry(app, telemetry)
    register_disk_info(app, disk_scans)
    register_widget(app, store, monitor, telemetry, health_monitor)

    register_status(app, ctx)
    register_access(app, ctx)
    register_web(app, ctx)
    register_objects(app, ctx)
    register_model(app, ctx)
    register_problems(app, ctx)
    chat_requests = register_chat(app, ctx)
    app.state.chat_requests = chat_requests
    lifecycle = MachineLifecycle(
        store,
        analyzer,
        collector,
        telemetry,
        health_monitor,
        outbox,
        disk_scans,
        chat_requests,
    )
    app.state.lifecycle = lifecycle
    register_machines(app, lifecycle)
    register_optimizer(app, store, monitor)
    register_ingest(app, store)
    register_enrollment(app, store)
    register_admin(app, ctx)
    return app
