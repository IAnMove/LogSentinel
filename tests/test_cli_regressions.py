"""CLI regressions: only temporary databases and stubbed external edges."""
from unittest.mock import AsyncMock

import pytest
from typer.testing import CliRunner

from logsentinel import cli
from logsentinel.config import Config
from logsentinel.core.engine import SentinelEngine
from logsentinel.core.models import LLMVerdict, LogEntry


@pytest.fixture
def isolated_cli(tmp_path, monkeypatch):
    cfg = Config()
    cfg.app.data_dir = str(tmp_path)
    cfg.behavior.enabled = False
    cfg.notifiers.desktop.enabled = False
    cfg.notifiers.file.enabled = False
    monkeypatch.setattr(cli.Config, "load", lambda *_: cfg)
    engines = []
    def factory(config, **kwargs):
        engine = SentinelEngine(config, **kwargs)
        engine.llm_client.analyze = AsyncMock(return_value=LLMVerdict(
            title="Regression alert", summary="synthetic", alert_needed=True))
        engine.dispatcher.dispatch = AsyncMock(return_value=[])
        engines.append(engine)
        return engine
    monkeypatch.setattr(cli, "SentinelEngine", factory)
    cards = []
    monkeypatch.setattr(cli, "print_alert_card", cards.append)
    return cfg, engines, cards


@pytest.mark.parametrize("command", ["scan", "simulate"])
@pytest.mark.parametrize("max_batch", [100, 1])
def test_batch_processes_and_displays_each_incident_once(isolated_cli, tmp_path, monkeypatch, command, max_batch):
    cfg, engines, cards = isolated_cli
    cfg.aggregator.max_batch_size = max_batch
    entry = LogEntry(service="sshd", message="Failed password for root", raw="synthetic")
    if command == "scan":
        target = tmp_path / "synthetic.log"
        target.write_text(entry.message + "\n")
        args = [command, str(target)]
    else:
        monkeypatch.setitem(cli.SCENARIOS, "regression", lambda: [entry])
        args = [command, "regression"]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.exception
    assert engines[0].llm_client.analyze.await_count == 1
    assert engines[0].dispatcher.dispatch.await_count == 1
    assert len(engines[0].memory_store.list_alerts()) == 1
    assert len(cards) == 1
    assert "No critical security alerts" not in result.output


@pytest.mark.parametrize("flags, expected", [([], True), (["--all"], False), (["--active-only"], True)])
def test_memory_list_flag_means_what_it_says(isolated_cli, monkeypatch, flags, expected):
    from unittest.mock import Mock
    store = Mock()
    store.list_rules.return_value = []
    monkeypatch.setattr(cli, "MemoryStore", lambda *_: store)
    result = CliRunner().invoke(cli.app, ["memory", "list", *flags])
    assert result.exit_code == 0, result.exception
    store.list_rules.assert_called_once_with(active_only=expected)


def test_config_show_redacts_transport_secrets_without_mutating_config(isolated_cli):
    cfg, _, _ = isolated_cli
    cfg.llm.api_key = "synthetic-api-secret"
    cfg.notifiers.telegram.bot_token = "synthetic-bot-secret"
    cfg.notifiers.discord.webhook_url = "https://example.invalid/synthetic-discord-secret"
    cfg.notifiers.slack.webhook_url = "https://example.invalid/synthetic-slack-secret"
    cfg.notifiers.generic_webhook.url = "https://example.invalid/synthetic-webhook-secret"
    cfg.notifiers.generic_webhook.headers = {"Authorization": "synthetic-header-secret"}
    original = cfg.model_dump()
    result = CliRunner().invoke(cli.app, ["config", "show"])
    assert result.exit_code == 0, result.exception
    for value in ["api", "bot", "discord", "slack", "webhook", "header"]:
        assert f"synthetic-{value}-secret" not in result.output
    assert "REDACTED" in result.output
    assert cfg.model_dump() == original


def test_run_surfaces_collector_failure_and_stops(isolated_cli, monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import Mock
    engine = SimpleNamespace(start=AsyncMock(), stop=AsyncMock(),
        raise_if_failed=Mock(side_effect=RuntimeError("synthetic collector failed")))
    monkeypatch.setattr(cli, "SentinelEngine", lambda *a, **kw: engine)
    ticks = 0
    async def tick(_):
        nonlocal ticks
        ticks += 1
        if ticks > 1:
            raise RuntimeError("health check was never called")
    monkeypatch.setattr(asyncio, "sleep", tick)
    result = CliRunner().invoke(cli.app, ["run"])
    assert result.exit_code != 0
    assert str(result.exception) == "synthetic collector failed"
    engine.raise_if_failed.assert_called_once()
    engine.stop.assert_awaited_once()


@pytest.mark.parametrize("failure", ["llm", "notifier", "database"])
def test_diagnostics_fail_exit_status_for_failed_component(isolated_cli, monkeypatch, failure):
    from types import SimpleNamespace
    from unittest.mock import Mock
    store = Mock()
    store.list_rules.return_value = store.list_alerts.return_value = []
    if failure == "database":
        store.list_rules.side_effect = RuntimeError("synthetic db failure")
    monkeypatch.setattr(cli, "MemoryStore", lambda *_: store)
    monkeypatch.setattr(cli.JournaldCollector, "is_available", lambda *_: False)
    engine = SimpleNamespace(
        llm_client=SimpleNamespace(check_health=AsyncMock(return_value={"status": "unhealthy" if failure == "llm" else "healthy"})),
        dispatcher=SimpleNamespace(test_all=AsyncMock(return_value={"synthetic": failure != "notifier"})),
    )
    monkeypatch.setattr(cli, "SentinelEngine", lambda *_: engine)
    result = CliRunner().invoke(cli.app, ["test"])
    assert result.exit_code == 1, result.output
