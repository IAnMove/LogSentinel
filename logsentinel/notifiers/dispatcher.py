"""Notification dispatcher coordinating multiple channels."""

from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Dict, List
from logsentinel.config import NotifiersConfig
from logsentinel.core.models import Alert, Severity
from logsentinel.notifiers.base import BaseNotifier
from logsentinel.notifiers.desktop import DesktopNotifier
from logsentinel.notifiers.discord import DiscordNotifier
from logsentinel.notifiers.file import FileNotifier
from logsentinel.notifiers.slack import SlackNotifier
from logsentinel.notifiers.telegram import TelegramNotifier
from logsentinel.notifiers.webhook import WebhookNotifier
from logsentinel.redact import redact


def scrubbed(alert: Alert) -> Alert:
    """A copy of the alert with recognisable credentials hidden.

    Everything a channel receives leaves the machine or lands on a screen. The
    log lines and the model's prose can both quote a password or a token.
    """
    copy = alert.model_copy(deep=True)
    verdict = copy.verdict
    verdict.title, verdict.summary = redact(verdict.title), redact(verdict.summary)
    for name in ("recommended_action", "reasoning"):
        if getattr(verdict, name):
            setattr(verdict, name, redact(getattr(verdict, name)))
    for entry in copy.incident.entries:
        entry.message, entry.raw = redact(entry.message), redact(entry.raw)
    return copy


class NotificationDispatcher:
    """Dispatches alerts to all configured and enabled notification channels."""

    def __init__(self, config: NotifiersConfig, default_file_path: Path):
        self.config = config
        self.timeout_seconds = 15.0
        self.min_severity = Severity(config.min_severity.upper())
        self.notifiers: List[BaseNotifier] = []

        if config.desktop.enabled:
            self.notifiers.append(DesktopNotifier(config.desktop))
        if config.telegram.enabled:
            self.notifiers.append(TelegramNotifier(config.telegram))
        if config.discord.enabled:
            self.notifiers.append(DiscordNotifier(config.discord))
        if config.slack.enabled:
            self.notifiers.append(SlackNotifier(config.slack))
        if config.generic_webhook.enabled:
            self.notifiers.append(WebhookNotifier(config.generic_webhook))
        if config.file.enabled:
            self.notifiers.append(FileNotifier(config.file, default_file_path))

    async def dispatch(self, alert: Alert) -> List[str]:
        """Send alert to all enabled notifiers if severity threshold is met."""
        if not alert.verdict.severity.is_at_least(self.min_severity):
            return []

        outgoing = scrubbed(alert)

        async def send_one(notifier):
            try:
                return await asyncio.wait_for(notifier.send(outgoing), self.timeout_seconds)
            except Exception:
                return False

        results = await asyncio.gather(*(send_one(n) for n in self.notifiers))
        successful_channels = [n.name for n, ok in zip(self.notifiers, results, strict=True) if ok]

        alert.channels_notified = successful_channels
        return successful_channels

    async def test_all(self) -> Dict[str, bool]:
        """Test all configured notification channels."""
        async def test_one(notifier):
            try:
                return await asyncio.wait_for(notifier.test(), self.timeout_seconds)
            except Exception:
                return False
        results = await asyncio.gather(*(test_one(n) for n in self.notifiers))
        return {n.name: bool(ok) for n, ok in zip(self.notifiers, results, strict=True)}
