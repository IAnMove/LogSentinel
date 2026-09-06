"""Configuration management for LogSentinel."""

from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
import yaml
from pydantic import BaseModel, Field, field_validator


def get_default_config_dir() -> Path:
    """Return standard config directory (~/.config/logsentinel)."""
    xdg_config = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config:
        return Path(xdg_config) / "logsentinel"
    return Path.home() / ".config" / "logsentinel"


def get_default_data_dir() -> Path:
    """Return standard data directory (~/.local/share/logsentinel)."""
    xdg_data = os.environ.get("XDG_DATA_HOME")
    if xdg_data:
        return Path(xdg_data) / "logsentinel"
    return Path.home() / ".local" / "share" / "logsentinel"


class AppConfig(BaseModel):
    """General application settings."""
    app_name: str = "LogSentinel"
    log_level: str = "INFO"
    data_dir: str = Field(default_factory=lambda: str(get_default_data_dir()))
    db_path: Optional[str] = None

    def get_resolved_db_path(self) -> Path:
        if self.db_path:
            return Path(self.db_path).expanduser().resolve()
        return Path(self.data_dir).expanduser().resolve() / "memory.db"

    def get_resolved_alerts_path(self) -> Path:
        return Path(self.data_dir).expanduser().resolve() / "alerts.jsonl"


class JournaldSourceConfig(BaseModel):
    """Systemd journal collection settings."""
    enabled: bool = True
    priority: str = "info"  # syslog priorities: 0=emerg, 1=alert, 2=crit, 3=err, 4=warning, 5=notice, 6=info
    units: List[str] = Field(default_factory=list)  # Empty means all systemd units
    extra_args: List[str] = Field(default_factory=list)


class FileSourceConfig(BaseModel):
    """File log tailing settings."""
    enabled: bool = True
    paths: List[str] = Field(default_factory=lambda: [
        "/var/log/auth.log",
        "/var/log/secure",
        "/var/log/syslog",
        "/var/log/messages",
        "/var/log/fail2ban.log",
        "/var/log/ufw.log",
        "/var/log/nginx/error.log",
    ])
    poll_interval_seconds: float = Field(default=1.0, gt=0, allow_inf_nan=False)


class SourcesConfig(BaseModel):
    """Log sources configuration."""
    journald: JournaldSourceConfig = Field(default_factory=JournaldSourceConfig)
    files: FileSourceConfig = Field(default_factory=FileSourceConfig)


class PrefilterConfig(BaseModel):
    """Fast triage and noise prefilter."""
    enabled: bool = True
    # Fast trigger keywords for security analysis
    security_keywords: List[str] = Field(default_factory=lambda: [
        "failed password", "invalid user", "authentication failure",
        "sudo:", "session opened for user root", "unauthorized",
        "break-in", "port scan", "apparmor=\"denied\"", "audit.*denied",
        "ufw block", "iptables denied", "segfault", "banned",
        "connection refused", "permission denied", "posible intrusion",
        "rejected", "unrecognized user"
    ])
    # Fast trigger keywords for system errors
    error_keywords: List[str] = Field(default_factory=lambda: [
        "out of memory", "oom-killer", "invoked oom-killer",
        "kernel panic", "read-only file system", "no space left on device",
        "i/o error", "disk error", "corrupted", "failed to start",
        "main process exited, code=dumped", "core dumped", "hardware error",
        "drastic", "emergency", "fatal", "ext4-fs error", "btrfs error", "critical temperature", "thermal_zone", "cpu throttled", "throttling", "overheat", "mce:", "machine check exception"
    ])
    # Noise keywords to skip immediately before wasting LLM calls
    noise_keywords: List[str] = Field(default_factory=lambda: [
        "using 0, ignoring 0",
        "errors from xkbcomp are not fatal",
        "systemd-logind: new session",
        "systemd-logind: removed session",
        "systemd: starting user slice",
        "systemd: stopped user slice",
        "chronyd[",
        "ntpd[",
        "ollama[",
        "api/tags",
    ])


class AggregatorConfig(BaseModel):
    """Log aggregation & debouncing window."""
    window_seconds: float = Field(default=3.0, gt=0, allow_inf_nan=False)
    max_batch_size: int = Field(default=15, ge=1)


class LLMConfig(BaseModel):
    """LLM provider and inference configuration."""
    provider: Literal["ollama", "openai"] = "ollama"  # "ollama" or "openai"
    base_url: str = "http://localhost:11434"
    model: str = "deepseek-r1:8b"
    api_key: Optional[str] = None
    timeout_seconds: float = Field(default=120.0, gt=0, allow_inf_nan=False)
    temperature: float = 0.1
    max_tokens: int = Field(default=1024, ge=1)


class DesktopNotifierConfig(BaseModel):
    """Desktop notification settings."""
    enabled: bool = True
    urgency_threshold: str = "LOW"  # Notify on LOW, MEDIUM, HIGH, CRITICAL
    expire_time_ms: int = 8000


class TelegramNotifierConfig(BaseModel):
    """Telegram bot notifications."""
    enabled: bool = False
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None


class DiscordNotifierConfig(BaseModel):
    """Discord webhook notifications."""
    enabled: bool = False
    webhook_url: Optional[str] = None


class SlackNotifierConfig(BaseModel):
    """Slack webhook notifications."""
    enabled: bool = False
    webhook_url: Optional[str] = None


class GenericWebhookConfig(BaseModel):
    """Generic HTTP POST webhook notifications."""
    enabled: bool = False
    url: Optional[str] = None
    headers: Dict[str, str] = Field(default_factory=dict)


class FileNotifierConfig(BaseModel):
    """Alerts persistence to JSONL file."""
    enabled: bool = True
    path: Optional[str] = None  # None uses AppConfig.get_resolved_alerts_path


class NotifiersConfig(BaseModel):
    """Notification targets configuration."""
    min_severity: Literal["DEBUG", "INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"] = "LOW"  # Minimum severity to dispatch notification
    desktop: DesktopNotifierConfig = Field(default_factory=DesktopNotifierConfig)
    telegram: TelegramNotifierConfig = Field(default_factory=TelegramNotifierConfig)
    discord: DiscordNotifierConfig = Field(default_factory=DiscordNotifierConfig)
    slack: SlackNotifierConfig = Field(default_factory=SlackNotifierConfig)
    generic_webhook: GenericWebhookConfig = Field(default_factory=GenericWebhookConfig)
    file: FileNotifierConfig = Field(default_factory=FileNotifierConfig)


class MemoryConfig(BaseModel):
    """Adaptive memory configuration."""
    enabled: bool = True
    max_semantic_rules_in_prompt: int = Field(default=15, ge=0)
    auto_learn_from_feedback: bool = True


class BehaviorConfig(BaseModel):
    """Conservative temporal profiles of successful SSH authentication."""
    enabled: bool = True
    timezone: str = "UTC"
    min_events: int = Field(default=20, ge=2)
    min_days: int = Field(default=5, ge=2)
    min_span_days: int = Field(default=14, ge=1)
    hour_tolerance: int = Field(default=1, ge=0, le=6)
    retention_days: int = Field(default=90, ge=14)
    max_events: int = Field(default=100000, ge=100)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown IANA timezone") from exc
        return value


class Config(BaseModel):
    """Root configuration for LogSentinel."""
    app: AppConfig = Field(default_factory=AppConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)
    prefilter: PrefilterConfig = Field(default_factory=PrefilterConfig)
    aggregator: AggregatorConfig = Field(default_factory=AggregatorConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    behavior: BehaviorConfig = Field(default_factory=BehaviorConfig)
    notifiers: NotifiersConfig = Field(default_factory=NotifiersConfig)

    @classmethod
    def load(cls, config_path: Optional[Path | str] = None) -> Config:
        """Load configuration from file or use defaults."""
        if config_path:
            path = Path(config_path).expanduser().resolve()
        else:
            path = get_default_config_dir() / "config.yaml"

        if not path.exists():
            if config_path:
                raise FileNotFoundError(f"Configuration not found: {path}")
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.model_validate({} if data is None else data)

    def save(self, config_path: Optional[Path | str] = None) -> Path:
        """Save configuration to YAML file."""
        if config_path:
            path = Path(config_path).expanduser().resolve()
        else:
            path = get_default_config_dir() / "config.yaml"

        path.parent.mkdir(parents=True, exist_ok=True)
        # Convert pydantic model to dict
        data = self.model_dump()
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        return path
