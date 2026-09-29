"""The objects every route module works with, built once per portal."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..analysis import Analyzer
from ..auth import SessionAuth
from ..build_info import running_build
from ..collect import Collector
from ..disk_info import DiskScans
from ..health import HealthMonitor
from ..monitor import Monitor
from ..notify import Outbox
from ..research import Researcher
from ..store import Store
from ..telemetry import Telemetry


@dataclass
class Context:
    build: Any
    store: Store
    collector: Collector
    analyzer: Analyzer
    monitor: Monitor
    researcher: Researcher
    telemetry: Telemetry
    disk_scans: DiskScans
    outbox: Outbox
    health_monitor: HealthMonitor
    auth: SessionAuth
    sessions: dict


def build_context(directory, background=True) -> Context:
    build = running_build()
    store = Store(directory)
    collector = Collector(store)
    analyzer = Analyzer(store)
    monitor = Monitor(store, analyzer, background)
    researcher = Researcher(store, analyzer)
    telemetry = Telemetry(store, analyzer)
    disk_scans = DiskScans(store, telemetry)
    outbox = Outbox(store)
    health_monitor = HealthMonitor(store, analyzer, monitor, telemetry, background)
    auth = SessionAuth(store)
    return Context(
        build=build,
        store=store,
        collector=collector,
        analyzer=analyzer,
        monitor=monitor,
        researcher=researcher,
        telemetry=telemetry,
        disk_scans=disk_scans,
        outbox=outbox,
        health_monitor=health_monitor,
        auth=auth,
        sessions=auth.sessions,
    )
