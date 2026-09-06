"""Persistent file notifier logging alerts in JSONL format."""

from __future__ import annotations
import json
from pathlib import Path
from logsentinel.config import FileNotifierConfig
from logsentinel.core.models import Alert
from logsentinel.notifiers.base import BaseNotifier


class FileNotifier(BaseNotifier):
    """Appends alert records as JSON lines to a log file."""

    name: str = "file"

    def __init__(self, config: FileNotifierConfig, default_path: Path):
        self.config = config
        self.path = Path(config.path).expanduser().resolve() if config.path else default_path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def send(self, alert: Alert) -> bool:
        if not self.config.enabled:
            return False

        try:
            record = {
                "id": alert.id,
                "timestamp": alert.created_at.isoformat(),
                "severity": alert.verdict.severity.value,
                "category": alert.verdict.category.value,
                "title": alert.verdict.title,
                "summary": alert.verdict.summary,
                "service": alert.incident.service,
                "count": alert.incident.count,
                "recommended_action": alert.verdict.recommended_action,
            }
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            return True
        except Exception:
            return False

    async def test(self) -> bool:
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps({"test": True, "app": "logsentinel"}) + "\n")
            return True
        except Exception:
            return False
