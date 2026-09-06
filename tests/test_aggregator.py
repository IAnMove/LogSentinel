"""Unit tests for LogAggregator."""

import asyncio
import pytest
from logsentinel.config import AggregatorConfig
from logsentinel.core.aggregator import LogAggregator
from logsentinel.core.models import Category, Incident, LogEntry


@pytest.mark.asyncio
async def test_aggregator_buffers_and_flushes():
    flushed_incidents = []

    async def _on_ready(inc: Incident):
        flushed_incidents.append(inc)

    config = AggregatorConfig(window_seconds=1.0, max_batch_size=5)
    aggregator = LogAggregator(config, on_incident_ready=_on_ready)

    # Ingest 3 similar entries
    for i in range(3):
        entry = LogEntry(
            service="sshd",
            message=f"Failed password for root from 1.1.1.1 port {2000 + i}",
            raw="raw",
        )
        await aggregator.add_entry(entry, Category.SECURITY)

    # Before flush
    assert len(flushed_incidents) == 0

    # Flush manually
    all_flushed = await aggregator.flush_all()
    assert len(all_flushed) == 1
    assert all_flushed[0].count == 3
    assert len(flushed_incidents) == 1


@pytest.mark.asyncio
async def test_aggregator_max_batch_size():
    flushed_incidents = []

    async def _on_ready(inc: Incident):
        flushed_incidents.append(inc)

    config = AggregatorConfig(window_seconds=10.0, max_batch_size=3)
    aggregator = LogAggregator(config, on_incident_ready=_on_ready)

    # Ingest 3 entries (hits max_batch_size=3)
    for i in range(3):
        entry = LogEntry(
            service="sudo",
            message=f"user not in sudoers {i}",
            raw="raw",
        )
        res = await aggregator.add_entry(entry, Category.SECURITY)

    assert len(flushed_incidents) == 1
    assert flushed_incidents[0].count == 3
