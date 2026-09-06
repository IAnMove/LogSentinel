"""Aggregates and debounces bursts of related log entries into Incidents."""

from __future__ import annotations
import asyncio
import time
from typing import Callable, Coroutine, Dict, List, Optional
from logsentinel.config import AggregatorConfig
from logsentinel.core.models import Category, Incident, LogEntry
from logsentinel.core.prefilter import PreFilter


class LogAggregator:
    """Groups high-frequency log lines within a time window into Incidents."""

    def __init__(
        self,
        config: AggregatorConfig,
        on_incident_ready: Optional[Callable[[Incident], Coroutine[None, None, None]]] = None,
    ):
        self.config = config
        self.on_incident_ready = on_incident_ready
        self._buffers: Dict[tuple[Optional[str], str, str], Incident] = {}
        self._last_flush_times: Dict[tuple[Optional[str], str, str], float] = {}
        self._lock = asyncio.Lock()
        self._running = False
        self._ticker_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the background flush ticker."""
        self._running = True
        self._ticker_task = asyncio.create_task(self._flush_ticker())

    async def stop(self) -> None:
        """Stop the aggregator and flush any remaining entries."""
        self._running = False
        if self._ticker_task:
            # A flush detaches its batch before awaiting callbacks. Cancelling the
            # ticker here would discard that batch, including unvisited incidents.
            await self._ticker_task
        await self.flush_all()

    async def add_entry(self, entry: LogEntry, category_hint: Category) -> Optional[Incident]:
        """Add a log entry to the aggregation buffer.
        
        Returns an Incident if immediate threshold is exceeded, else None.
        """
        sig = PreFilter.extract_signature(entry)
        key = (entry.hostname, entry.service, sig)

        async with self._lock:
            now = time.monotonic()
            if key not in self._buffers:
                incident = Incident(
                    service=entry.service,
                    category_hint=category_hint,
                    signature=sig,
                    entries=[entry],
                    first_seen=entry.timestamp,
                    last_seen=entry.timestamp,
                    hostname=entry.hostname,
                )
                self._buffers[key] = incident
                self._last_flush_times[key] = now
            else:
                incident = self._buffers[key]
                incident.add_entry(entry)

            # Check if reached max batch size
            if len(incident.entries) >= self.config.max_batch_size:
                ready_incident = self._buffers.pop(key)
                self._last_flush_times.pop(key, None)
            else:
                ready_incident = None

        # User callbacks may reenter the aggregator; never await them under the lock.
        if ready_incident is not None and self.on_incident_ready:
            await self.on_incident_ready(ready_incident)
        return ready_incident

    async def _flush_ticker(self) -> None:
        """Periodically flushes buffers whose window has expired."""
        while self._running:
            await asyncio.sleep(0.5)
            await self._check_and_flush_expired()

    async def _check_and_flush_expired(self) -> List[Incident]:
        """Check and flush expired buffers."""
        now = time.monotonic()
        to_flush: List[Incident] = []

        async with self._lock:
            keys_to_remove = []
            for key, last_time in self._last_flush_times.items():
                if now - last_time >= self.config.window_seconds:
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                if key in self._buffers:
                    to_flush.append(self._buffers.pop(key))
                self._last_flush_times.pop(key, None)

        for incident in to_flush:
            if self.on_incident_ready:
                await self.on_incident_ready(incident)

        return to_flush

    async def flush_all(self) -> List[Incident]:
        """Flush all pending buffers immediately."""
        async with self._lock:
            all_incidents = list(self._buffers.values())
            self._buffers.clear()
            self._last_flush_times.clear()

        for incident in all_incidents:
            if self.on_incident_ready:
                await self.on_incident_ready(incident)

        return all_incidents
