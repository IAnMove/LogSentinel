"""Base collector interface."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import AsyncGenerator
from logsentinel.core.models import LogEntry


class BaseCollector(ABC):
    """Abstract base class for log collectors."""

    @abstractmethod
    def stream(self) -> AsyncGenerator[LogEntry, None]:
        """Asynchronously yield LogEntry instances as they arrive.

        Implementations are async generators, so calling stream() returns the
        generator directly; it is not a coroutine to await first."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop log collection."""
        pass
