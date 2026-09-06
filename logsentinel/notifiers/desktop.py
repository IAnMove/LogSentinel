"""Desktop notification dispatcher using libnotify / notify-send."""

from __future__ import annotations
import asyncio
import os
import shutil
from typing import Optional
from logsentinel.config import DesktopNotifierConfig
from logsentinel.core.models import Alert, Severity
from logsentinel.notifiers.base import BaseNotifier


class DesktopNotifier(BaseNotifier):
    """Sends native Linux desktop notifications via notify-send."""

    name: str = "desktop"

    def __init__(self, config: DesktopNotifierConfig):
        self.config = config
        self._notify_send_path = shutil.which("notify-send")

    def _is_gui_available(self) -> bool:
        """Check if an active graphical display session is detected."""
        return bool(
            os.environ.get("DISPLAY")
            or os.environ.get("WAYLAND_DISPLAY")
            or os.environ.get("DBUS_SESSION_BUS_ADDRESS")
        )

    async def send(self, alert: Alert) -> bool:
        if not self.config.enabled or not self._notify_send_path:
            return False

        if not self._is_gui_available():
            return False

        if not alert.verdict.severity.is_at_least(self.config.urgency_threshold):
            return False

        if alert.verdict.severity in (Severity.CRITICAL, Severity.HIGH):
            urgency = "critical"
            icon = "dialog-error"
        elif alert.verdict.severity == Severity.MEDIUM:
            urgency = "normal"
            icon = "dialog-warning"
        else:
            urgency = "low"
            icon = "dialog-information"

        title = f"🛡️ [{alert.verdict.severity.value}] {alert.verdict.title}"
        body_parts = [alert.verdict.summary]
        if alert.verdict.recommended_action:
            body_parts.append(f"\n💡 Action: {alert.verdict.recommended_action}")
        body = "\n".join(body_parts)

        cmd = [
            self._notify_send_path,
            "-u", urgency,
            "-a", "LogSentinel",
            "-i", icon,
            "-t", str(self.config.expire_time_ms),
            title,
            body,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            try:
                await proc.communicate()
            finally:
                if proc.returncode is None:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    await proc.wait()
            return proc.returncode == 0
        except Exception:
            return False

    async def test(self) -> bool:
        if not self._notify_send_path:
            return False
        cmd = [
            self._notify_send_path,
            "-u", "normal",
            "-a", "LogSentinel",
            "-i", "security-high",
            "🛡️ LogSentinel Test",
            "Desktop notifications are properly configured and operational.",
        ]
        try:
            proc = await asyncio.create_subprocess_exec(*cmd)
            try:
                await proc.communicate()
            finally:
                if proc.returncode is None:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    await proc.wait()
            return proc.returncode == 0
        except Exception:
            return False
