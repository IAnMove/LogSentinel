"""Base abstract class for notification channels."""

from __future__ import annotations
from abc import ABC, abstractmethod
import httpx
from logsentinel.core.models import Alert


def outbound_client(timeout: float = 10.0) -> httpx.AsyncClient:
    """HTTP client for a destination taken from configuration.

    The portal's notifier already refuses cloud metadata addresses, ignores
    proxy variables and never follows redirects; the older channels get the
    same transport instead of a bare AsyncClient.
    """
    from logsentinel.portal.network import CheckedAsyncTransport

    return httpx.AsyncClient(
        transport=CheckedAsyncTransport(), timeout=timeout,
        trust_env=False, follow_redirects=False,
    )


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
