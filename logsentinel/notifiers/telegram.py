"""Telegram bot notification dispatcher."""

from __future__ import annotations
import html
from typing import Optional
import httpx
from logsentinel.config import TelegramNotifierConfig
from logsentinel.core.models import Alert, Severity
from logsentinel.notifiers.base import BaseNotifier


class TelegramNotifier(BaseNotifier):
    """Sends formatted HTML alerts to Telegram channels/chats."""

    name: str = "telegram"

    def __init__(self, config: TelegramNotifierConfig):
        self.config = config

    def _format_message(self, alert: Alert) -> str:
        sev = alert.verdict.severity
        emoji = {
            Severity.CRITICAL: "🚨",
            Severity.HIGH: "🔴",
            Severity.MEDIUM: "🟡",
            Severity.LOW: "🔵",
            Severity.INFO: "ℹ️",
        }.get(sev, "⚠️")

        title = html.escape(alert.verdict.title)
        summary = html.escape(alert.verdict.summary)
        service = html.escape(alert.incident.service)
        cat = html.escape(alert.verdict.category.value)

        lines = [
            f"{emoji} <b>[LogSentinel Alert: {sev.value}]</b>",
            f"<b>Title:</b> {title}",
            f"<b>Service:</b> <code>{service}</code> | <b>Category:</b> {cat}",
            f"<b>Events count:</b> {alert.incident.count}",
            f"",
            f"<b>Summary:</b>",
            f"{summary}",
        ]

        if alert.verdict.recommended_action:
            action = html.escape(alert.verdict.recommended_action)
            lines.extend([
                f"",
                f"<b>Recommended Action:</b>",
                f"<code>{action}</code>",
            ])

        lines.extend([
            f"",
            f"<i>Alert ID:</i> <code>{alert.id}</code>",
            f"<i>To ignore future occurrences:</i> <code>logsentinel alerts dismiss {alert.id} --always</code>",
        ])

        return "\n".join(lines)

    async def send(self, alert: Alert) -> bool:
        if not self.config.enabled or not self.config.bot_token or not self.config.chat_id:
            return False

        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": self._format_message(alert),
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                return resp.status_code == 200
        except Exception:
            return False

    async def test(self) -> bool:
        if not self.config.bot_token or not self.config.chat_id:
            return False
        url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"
        payload = {
            "chat_id": self.config.chat_id,
            "text": "🛡️ <b>LogSentinel</b>: Test notification successful!",
            "parse_mode": "HTML",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                return resp.status_code == 200
        except Exception:
            return False
