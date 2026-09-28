"""The older command-line pipeline gets the same output protections as the portal."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from logsentinel.config import (
    DesktopNotifierConfig, DiscordNotifierConfig, GenericWebhookConfig, LLMConfig,
    NotifiersConfig, SlackNotifierConfig, TelegramNotifierConfig,
)
from logsentinel.core.models import Alert, Incident, LLMVerdict, LogEntry, Severity
from logsentinel.llm.prompts import build_analysis_prompt
from logsentinel.notifiers.desktop import DesktopNotifier
from logsentinel.notifiers.discord import DiscordNotifier
from logsentinel.notifiers.dispatcher import NotificationDispatcher, scrubbed
from logsentinel.notifiers.slack import SlackNotifier
from logsentinel.notifiers.telegram import TelegramNotifier
from logsentinel.notifiers.webhook import WebhookNotifier

SECRET_LINE = "login failed for api with password=hunter2 and Authorization: Bearer abcdef123456"


def alert(**verdict):
    entry = LogEntry(service="api", message=SECRET_LINE, raw=SECRET_LINE, hostname="h")
    incident = Incident(service="api", signature="s", entries=[entry])
    fields = dict(title="Login failures", summary="Saw " + SECRET_LINE, severity=Severity.HIGH,
                  recommended_action="Rotate password=hunter2", reasoning="token: abcdefgh12345678")
    fields.update(verdict)
    return Alert(incident=incident, verdict=LLMVerdict(**fields))


def test_scrubbed_copy_hides_credentials_and_leaves_the_original_alone():
    original = alert()
    copy = scrubbed(original)
    text = copy.model_dump_json()
    assert "hunter2" not in text and "abcdef123456" not in text
    assert "hunter2" in original.model_dump_json()


def test_prompt_sent_to_the_model_does_not_carry_credentials():
    incident = alert().incident
    prompt = build_analysis_prompt(incident)
    assert "hunter2" not in prompt and "abcdef123456" not in prompt
    assert "login failed" in prompt


@pytest.mark.asyncio
async def test_every_channel_receives_the_scrubbed_alert(tmp_path):
    seen = []

    async def record(delivered):
        seen.append(delivered.model_dump_json())
        return True

    config = NotifiersConfig()
    config.desktop.enabled = config.file.enabled = False
    dispatcher = NotificationDispatcher(config, tmp_path / "unused")
    dispatcher.notifiers = [SimpleNamespace(name="a", send=record), SimpleNamespace(name="b", send=record)]
    await dispatcher.dispatch(alert())
    assert len(seen) == 2 and all("hunter2" not in text for text in seen)


@pytest.fixture
def requests_seen(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **{k: v for k, v in kw.items() if k != "transport"}),
    )
    return seen


@pytest.mark.asyncio
async def test_slack_treats_model_text_as_data_not_markup(requests_seen):
    notifier = SlackNotifier(SlackNotifierConfig(enabled=True, webhook_url="https://hooks.example.invalid/x"))
    hostile = alert(summary="<!channel> see <https://evil.example|your invoice>", recommended_action="<!here>")
    assert await notifier.send(hostile)
    body = json.loads(requests_seen[0].content)
    kinds = {part["type"] for block in body["blocks"] for part in [block.get("text", {})] + block.get("fields", []) if part}
    assert "mrkdwn" not in kinds
    assert "<!channel>" in json.dumps(body)  # present only as inert plain text


@pytest.mark.asyncio
async def test_discord_never_pings(requests_seen):
    notifier = DiscordNotifier(DiscordNotifierConfig(enabled=True, webhook_url="https://discord.example.invalid/x"))
    assert await notifier.send(alert(summary="@everyone look"))
    assert json.loads(requests_seen[0].content)["allowed_mentions"] == {"parse": []}
    assert await notifier.test()
    assert json.loads(requests_seen[1].content)["allowed_mentions"] == {"parse": []}


@pytest.mark.asyncio
async def test_desktop_text_that_starts_with_a_dash_is_not_an_option(monkeypatch):
    notifier = DesktopNotifier(DesktopNotifierConfig())
    notifier._notify_send_path = "synthetic-notify"
    monkeypatch.setattr(notifier, "_is_gui_available", lambda: True)
    spawn = AsyncMock(return_value=SimpleNamespace(communicate=AsyncMock(), returncode=0))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    assert await notifier.send(alert(title="--hint=int:x:1", summary="-u critical"))
    argv = list(spawn.await_args.args)
    separator = argv.index("--")
    # The dash-led body sits after "--", so notify-send reads it as text; the
    # options it does interpret all come before the separator.
    assert argv[separator + 2].startswith("-u critical")
    assert argv.index("-u") < separator and argv.index("-a") < separator
    assert len(argv) == separator + 3


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["metadata.google.internal", "169.254.169.254", "168.63.129.16"])
async def test_configured_channels_cannot_be_pointed_at_cloud_metadata(target):
    hooks = [
        SlackNotifier(SlackNotifierConfig(enabled=True, webhook_url=f"http://{target}/hook")),
        WebhookNotifier(GenericWebhookConfig(enabled=True, url=f"http://{target}/hook")),
    ]
    for hook in hooks:
        assert await hook.send(alert()) is False


@pytest.mark.asyncio
async def test_proxy_variables_are_ignored(monkeypatch, requests_seen):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
    notifier = TelegramNotifier(TelegramNotifierConfig(enabled=True, bot_token="123456:abcdefghijklmnopqrstuvwxyz012345678", chat_id="1"))
    assert await notifier.send(alert())
    assert requests_seen[0].url.host == "api.telegram.org"
