"""Base abstract class for notification channels."""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
from logsentinel.core.models import Alert


class BaseNotifier(ABC):
    """Abstract interface for alert notifiers."""

    name: str = "base"

    @abstractmethod
    async def send(self, alert: Alert) -> bool:
        """Send alert notification. Returns True if successful."""
        pass

    @abstractmethod
    async def test(self) -> bool:
        """Send a test notification to verify channel configuration."""
        pass
