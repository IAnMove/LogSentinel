"""Slack incoming webhook notification dispatcher."""

from __future__ import annotations
from logsentinel.config import SlackNotifierConfig
from logsentinel.core.models import Alert
from logsentinel.notifiers.base import BaseNotifier, outbound_client


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
                    {"type": "plain_text", "text": f"Service: {alert.incident.service}"},
                    {"type": "plain_text", "text": f"Category: {alert.verdict.category.value}"},
                    {"type": "plain_text", "text": f"Count: {alert.incident.count}"},
                    {"type": "plain_text", "text": f"Alert ID: {alert.id}"},
                ],
            },
            {
                "type": "section",
                # Text written by the model or copied from a log is data: in mrkdwn it
                # could ping a channel (<!channel>) or draw a link that hides its target.
                "text": {
                    "type": "plain_text",
                    "text": f"Summary:\n{alert.verdict.summary}",
                },
            },
        ]

        if alert.verdict.recommended_action:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "plain_text",
                    "text": f"Recommended Action:\n{alert.verdict.recommended_action}",
                },
            })

        payload = {"blocks": blocks}

        try:
            async with outbound_client(10.0) as client:
                resp = await client.post(self.config.webhook_url, json=payload)
                return resp.status_code == 200
        except Exception:
            return False

    async def test(self) -> bool:
        if not self.config.webhook_url:
            return False
        payload = {"text": "🛡️ LogSentinel: Slack notifications test successful!"}
        try:
            async with outbound_client(10.0) as client:
                resp = await client.post(self.config.webhook_url, json=payload)
                return resp.status_code == 200
        except Exception:
            return False
