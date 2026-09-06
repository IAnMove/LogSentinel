"""Base collector interface."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import AsyncGenerator
from logsentinel.core.models import LogEntry


class BaseCollector(ABC):
    """Abstract base class for log collectors."""

    @abstractmethod
    async def stream(self) -> AsyncGenerator[LogEntry, None]:
        """Asynchronously yield LogEntry instances as they arrive."""
        pass

    @abstractmethod
    async def stop(self) -> None:
        """Stop log collection."""
        pass
