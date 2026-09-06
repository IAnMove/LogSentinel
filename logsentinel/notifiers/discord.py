"""Discord webhook notification dispatcher."""

from __future__ import annotations
from datetime import datetime, timezone
import httpx
from logsentinel.config import DiscordNotifierConfig
from logsentinel.core.models import Alert, Severity
from logsentinel.notifiers.base import BaseNotifier


class DiscordNotifier(BaseNotifier):
    """Sends rich Discord embed cards via webhook."""

    name: str = "discord"

    def __init__(self, config: DiscordNotifierConfig):
        self.config = config

    def _get_color(self, sev: Severity) -> int:
        colors = {
            Severity.CRITICAL: 0xE74C3C,  # Red
            Severity.HIGH: 0xE67E22,      # Orange
            Severity.MEDIUM: 0xF1C40F,    # Yellow
            Severity.LOW: 0x3498DB,       # Blue
            Severity.INFO: 0x2ECC71,      # Green
        }
        return colors.get(sev, 0x95A5A6)

    async def send(self, alert: Alert) -> bool:
        if not self.config.enabled or not self.config.webhook_url:
            return False

        color = self._get_color(alert.verdict.severity)
        embed = {
            "title": f"🛡️ [{alert.verdict.severity.value}] {alert.verdict.title}",
            "description": alert.verdict.summary,
            "color": color,
            "fields": [
                {"name": "Service", "value": f"`{alert.incident.service}`", "inline": True},
                {"name": "Category", "value": alert.verdict.category.value, "inline": True},
                {"name": "Events Count", "value": str(alert.incident.count), "inline": True},
            ],
            "footer": {
                "text": f"LogSentinel • Alert ID: {alert.id} • Dismiss: logsentinel alerts dismiss {alert.id} --always",
            },
            "timestamp": alert.created_at.isoformat(),
        }

        if alert.verdict.recommended_action:
            embed["fields"].append({
                "name": "💡 Recommended Action",
                "value": f"```{alert.verdict.recommended_action}```",
                "inline": False,
            })

        payload = {
            "username": "LogSentinel AI",
            "embeds": [embed],
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.config.webhook_url, json=payload)
                return resp.status_code in (200, 204)
        except Exception:
            return False

    async def test(self) -> bool:
        if not self.config.webhook_url:
            return False
        payload = {
            "username": "LogSentinel AI",
            "embeds": [{
                "title": "🛡️ LogSentinel Test",
                "description": "Discord webhook notifications are properly configured!",
                "color": 0x2ECC71,
            }],
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.config.webhook_url, json=payload)
                return resp.status_code in (200, 204)
        except Exception:
            return False
