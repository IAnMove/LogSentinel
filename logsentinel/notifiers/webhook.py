"""Generic HTTP webhook notification dispatcher."""

from __future__ import annotations
import httpx
from logsentinel.config import GenericWebhookConfig
from logsentinel.core.models import Alert
from logsentinel.notifiers.base import BaseNotifier


class WebhookNotifier(BaseNotifier):
    """Posts full alert payload to custom HTTP endpoint."""

    name: str = "webhook"

    def __init__(self, config: GenericWebhookConfig):
        self.config = config

    async def send(self, alert: Alert) -> bool:
        if not self.config.enabled or not self.config.url:
            return False

        payload = {
            "id": alert.id,
            "created_at": alert.created_at.isoformat(),
            "severity": alert.verdict.severity.value,
            "category": alert.verdict.category.value,
            "title": alert.verdict.title,
            "summary": alert.verdict.summary,
            "recommended_action": alert.verdict.recommended_action,
            "service": alert.incident.service,
            "count": alert.incident.count,
            "raw_entries_sample": [e.message for e in alert.incident.entries[:5]],
        }

        headers = {"Content-Type": "application/json", **self.config.headers}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.config.url, json=payload, headers=headers)
                return 200 <= resp.status_code < 300
        except Exception:
            return False

    async def test(self) -> bool:
        if not self.config.url:
            return False
        payload = {"event": "test", "app": "logsentinel"}
        headers = {"Content-Type": "application/json", **self.config.headers}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.config.url, json=payload, headers=headers)
                return 200 <= resp.status_code < 300
        except Exception:
            return False
