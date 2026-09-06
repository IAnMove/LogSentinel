"""Regression tests for aggregation boundaries and callback delivery."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import logsentinel.core.aggregator as aggregator_module
from logsentinel.config import AggregatorConfig
from logsentinel.core.aggregator import LogAggregator
from logsentinel.core.models import Category, LogEntry


def make_entry(**kwargs):
    return LogEntry(service="sshd", message="Failed password", raw="raw", **kwargs)


@pytest.mark.asyncio
async def test_max_batch_callback_can_reenter_add_entry():
    delivered = []
    followup = make_entry()

    async def on_ready(incident):
        delivered.append(incident)
        if len(delivered) == 1:
            await aggregator.add_entry(followup, Category.SECURITY)

    aggregator = LogAggregator(AggregatorConfig(max_batch_size=2), on_ready)
    await aggregator.add_entry(make_entry(), Category.SECURITY)
    ready = await asyncio.wait_for(
        aggregator.add_entry(make_entry(), Category.SECURITY), timeout=1
    )
    assert delivered == [ready]
    assert ready.count == 2
    remaining = await aggregator.flush_all()
    assert len(remaining) == 1
    assert remaining[0].entries == [followup]


@pytest.mark.asyncio
async def test_initial_incident_bounds_use_event_timestamp():
    event_time = datetime(2020, 1, 2, 3, 4, tzinfo=timezone.utc)
    aggregator = LogAggregator(AggregatorConfig())
    await aggregator.add_entry(make_entry(timestamp=event_time), Category.SECURITY)
    incident, = await aggregator.flush_all()
    assert incident.first_seen == event_time
    assert incident.last_seen == event_time


@pytest.mark.asyncio
async def test_out_of_order_events_keep_minimum_and_maximum_timestamps():
    times = [datetime(2020, 1, day, tzinfo=timezone.utc) for day in (2, 1, 3, 2)]
    aggregator = LogAggregator(AggregatorConfig())
    for timestamp in times:
        await aggregator.add_entry(make_entry(timestamp=timestamp), Category.SECURITY)
    incident, = await aggregator.flush_all()
    assert incident.first_seen == min(times)
    assert incident.last_seen == max(times)
    assert incident.count == len(times)


@pytest.mark.asyncio
async def test_same_signature_is_separated_by_hostname():
    aggregator = LogAggregator(AggregatorConfig())
    entries = [make_entry(hostname=host) for host in ("host-a", "host-b", None, "")]
    for entry in entries:
        await aggregator.add_entry(entry, Category.SECURITY)
    incidents = await aggregator.flush_all()
    assert len(incidents) == len(entries)
    assert {incident.hostname for incident in incidents} == {"host-a", "host-b", None, ""}
    assert all(incident.count == 1 for incident in incidents)
    assert {incident.entries[0].id for incident in incidents} == {entry.id for entry in entries}


@pytest.mark.asyncio
@pytest.mark.parametrize("wall_jump", [-3600, 3600])
async def test_window_uses_monotonic_elapsed_time(monkeypatch, wall_jump):
    clock = {"elapsed": 100.0, "wall": 10000.0}
    monkeypatch.setattr(
        aggregator_module,
        "time",
        SimpleNamespace(monotonic=lambda: clock["elapsed"], time=lambda: clock["wall"]),
    )
    aggregator = LogAggregator(AggregatorConfig(window_seconds=10))
    entry = make_entry()
    await aggregator.add_entry(entry, Category.SECURITY)
    clock["wall"] += wall_jump
    clock["elapsed"] += 9
    assert await aggregator._check_and_flush_expired() == []
    clock["elapsed"] += 1
    incident, = await aggregator._check_and_flush_expired()
    assert incident.entries == [entry]
    assert await aggregator.flush_all() == []


@pytest.mark.asyncio
async def test_stop_preserves_inflight_ticker_flush(monkeypatch):
    clock = {"now": 100.0}
    monkeypatch.setattr(
        aggregator_module, "time", SimpleNamespace(monotonic=lambda: clock["now"])
    )
    entered = asyncio.Event()
    release = asyncio.Event()
    delivered = []

    async def on_ready(incident):
        entered.set()
        await release.wait()
        delivered.append(incident)

    aggregator = LogAggregator(AggregatorConfig(window_seconds=1), on_ready)
    entries = [make_entry(hostname=host) for host in ("host-a", "host-b")]
    for entry in entries:
        await aggregator.add_entry(entry, Category.SECURITY)
    clock["now"] += 1
    await aggregator.start()
    stopping = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        stopping = asyncio.create_task(aggregator.stop())
        await asyncio.sleep(0)  # Let stop run while the callback is suspended.
        release.set()
        await asyncio.wait_for(stopping, timeout=1)
        assert {incident.entries[0].id for incident in delivered} == {
            entry.id for entry in entries
        }
        assert len(delivered) == 2
        assert await aggregator.flush_all() == []
    finally:
        release.set()
        if stopping is not None:
            await asyncio.gather(stopping, return_exceptions=True)
        await aggregator.stop()
