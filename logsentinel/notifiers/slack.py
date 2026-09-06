"""Slack incoming webhook notification dispatcher."""

from __future__ import annotations
import httpx
from logsentinel.config import SlackNotifierConfig
from logsentinel.core.models import Alert
from logsentinel.notifiers.base import BaseNotifier


class SlackNotifier(BaseNotifier):
    """Sends formatted blocks to Slack incoming webhooks."""

    name: str = "slack"

    def __init__(self, config: SlackNotifierConfig):
        self.config = config

    async def send(self, alert: Alert) -> bool:
        if not self.config.enabled or not self.config.webhook_url:
            return False

        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"🛡️ [{alert.verdict.severity.value}] {alert.verdict.title}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Service:* `{alert.incident.service}`"},
                    {"type": "mrkdwn", "text": f"*Category:* {alert.verdict.category.value}"},
                    {"type": "mrkdwn", "text": f"*Count:* {alert.incident.count}"},
                    {"type": "mrkdwn", "text": f"*Alert ID:* `{alert.id}`"},
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Summary:*\n{alert.verdict.summary}",
                },
            },
        ]

        if alert.verdict.recommended_action:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Recommended Action:*\n```{alert.verdict.recommended_action}```",
                },
            })

        payload = {"blocks": blocks}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.config.webhook_url, json=payload)
                return resp.status_code == 200
        except Exception:
            return False

    async def test(self) -> bool:
        if not self.config.webhook_url:
            return False
        payload = {"text": "🛡️ LogSentinel: Slack notifications test successful!"}
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(self.config.webhook_url, json=payload)
                return resp.status_code == 200
        except Exception:
            return False
