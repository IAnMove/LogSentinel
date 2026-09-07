"""Validated portal contracts. Secrets never belong to public representations."""

from __future__ import annotations
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field, ConfigDict, field_validator, model_validator
from logsentinel.config import LLMConfig


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Machine(Model):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["local", "imported"] = "imported"
    hostname: str = Field(default="", max_length=255)
    os: str = Field(default="", max_length=200)
    timezone: str = "UTC"
    notes: str = Field(default="", max_length=4000)

    @field_validator("timezone")
    @classmethod
    def timezone_valid(cls, value):
        try:
            ZoneInfo(value)
        except Exception as exc:
            raise ValueError("Unknown timezone") from exc
        return value


class Source(Model):
    machine_id: str
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["file", "folder", "journald", "push", "metrics", "health"] = "file"
    path: str = Field(default="", max_length=4096)
    pattern: str = Field(default="*.log*", min_length=1, max_length=200)
    enabled: bool = False
    history: bool = False
    multiline: bool = False
    max_batch_bytes: int = Field(default=2_000_000, ge=1024, le=8_000_000)
    analysis_mode: Literal["all", "priority", "keywords", "adaptive"] = "all"
    priority_ceiling: int = Field(default=4, ge=0, le=7)
    trigger_terms: str = Field(
        default="error\ncritical\nwarning\nfailed\nfailure\npanic\nexception\nunauthorized\npermission denied\nout of memory\nno space left on device",
        max_length=4000,
    )
    context_minutes: int = Field(default=5, ge=0, le=60)
    heartbeat_timeout_seconds: int = Field(default=0, ge=0, le=86400)

    @model_validator(mode="after")
    def valid_path(self):
        if self.kind in ("file", "folder") and not self.path:
            raise ValueError("A path is required")
        if ".." in self.pattern or "/" in self.pattern or "\\" in self.pattern:
            raise ValueError("Pattern must match filenames within the selected folder")
        return self


class Settings(Model):
    enabled: bool = False
    language: Literal["en", "es"] = "en"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    interval_seconds: int = Field(default=300, ge=5, le=86400)
    context_tokens: int = Field(default=8192, ge=2048, le=1_000_000)
    input_budget: int = Field(default=5000, ge=512, le=500_000)
    max_events: int = Field(default=500, ge=10, le=5000)
    max_calls: int = Field(default=3, ge=1, le=10)
    retention_days: int = Field(default=30, ge=1, le=3650)
    disk_limit_mb: int = Field(default=1024, ge=32, le=1_000_000)
    sensitivity: Literal["light", "balanced", "thorough"] = "balanced"
    remote_allowed: bool = False
    health_alerts: bool = True
    health_grace_seconds: int = Field(default=30, ge=5, le=3600)
    storage_warning_percent: int = Field(default=80, ge=50, le=99)

    @model_validator(mode="after")
    def budgets(self):
        if self.input_budget + self.llm.max_tokens + 1024 > self.context_tokens:
            raise ValueError(
                "Context must reserve input, output and 1024 tokens for instructions"
            )
        check_url(self.llm.base_url)
        return self


def check_url(value):
    p = urlsplit(value)
    if (
        p.scheme not in ("http", "https")
        or not p.hostname
        or p.username
        or p.password
        or p.fragment
    ):
        raise ValueError("Use an HTTP(S) URL without embedded credentials or fragment")
    return value


class Destination(Model):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal[
        "system", "telegram", "slack", "discord", "hermes", "n8n", "webhook", "file"
    ]
    enabled: bool = False
    machine_id: str = ""
    source_id: str = ""
    min_severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] = "MEDIUM"
    url: str = ""
    token: str = ""
    chat_id: str = ""
    secret: str = ""
    headers: dict[str, str] = Field(default_factory=dict)
    path: str = ""
    cooldown_seconds: int = Field(default=300, ge=0, le=86400)
    rotation_mb: int = Field(default=10, ge=1, le=1024)
    keep_archives: int = Field(default=3, ge=1, le=50)

    @model_validator(mode="after")
    def complete(self):
        if self.url:
            check_url(self.url)
        if self.enabled:
            if self.kind == "telegram" and not (self.token and self.chat_id):
                raise ValueError("Telegram requires token and chat ID")
            if (
                self.kind in ("slack", "discord", "hermes", "n8n", "webhook")
                and not self.url
            ):
                raise ValueError("Webhook URL required")
            if self.kind == "hermes" and not self.secret:
                raise ValueError("Hermes signing secret required")
        return self


class Rule(Model):
    name: str = Field(min_length=1, max_length=120)
    action: Literal["mute", "exclude"] = "mute"
    kind: Literal["problem", "regex", "ip"] = "regex"
    pattern: str = Field(min_length=1, max_length=1000)
    machine_id: str = ""
    source_id: str = ""
    enabled: bool = True
    expires_at: float | None = None


class Finding(Model):
    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4000)
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
    category: str = Field(min_length=1, max_length=100)
    evidence_ids: list[str] = Field(min_length=1, max_length=100)
    reasoning: str = Field(default="", max_length=5000)
    next_steps: str = Field(default="", max_length=4000)

    @field_validator("next_steps", mode="before")
    @classmethod
    def normalize_steps(cls, value):
        # Small local models commonly return a list of checks. Accept only
        # strings, retain the length bound and never coerce arbitrary objects.
        if isinstance(value, list) and all(isinstance(step, str) for step in value):
            return "\n".join("- " + step for step in value)
        return value


class Verdict(Model):
    findings: list[Finding] = Field(max_length=30)
