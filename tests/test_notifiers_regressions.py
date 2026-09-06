"""No desktop or network effects: all transport edges are fake."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from logsentinel.config import NotifiersConfig, DesktopNotifierConfig
from logsentinel.core.models import Alert, Incident, LLMVerdict, Severity
from logsentinel.notifiers.dispatcher import NotificationDispatcher
from logsentinel.notifiers.desktop import DesktopNotifier


def synthetic_alert(severity=Severity.LOW):
    return Alert(incident=Incident(service="synthetic", signature="test"),
                 verdict=LLMVerdict(title="test", summary="test", severity=severity))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["dispatch", "test_all"])
async def test_hung_notifier_is_bounded_and_does_not_block_others(tmp_path, operation):
    config = NotifiersConfig()
    config.desktop.enabled = config.file.enabled = False
    dispatcher = NotificationDispatcher(config, tmp_path / "unused")
    dispatcher.timeout_seconds = 0.01
    reached = asyncio.Event()
    cancelled = asyncio.Event()
    async def hung(*_):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    async def healthy(*_):
        reached.set()
        return True
    dispatcher.notifiers = [
        SimpleNamespace(name="hung", send=hung, test=hung),
        SimpleNamespace(name="healthy", send=healthy, test=healthy),
    ]
    coro = dispatcher.dispatch(synthetic_alert()) if operation == "dispatch" else dispatcher.test_all()
    task = asyncio.create_task(coro)
    try:
        await asyncio.wait_for(reached.wait(), 0.2)
        result = await asyncio.wait_for(task, 0.2)
        assert result == (["healthy"] if operation == "dispatch" else {"hung": False, "healthy": True})
        assert cancelled.is_set()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_desktop_respects_its_own_threshold(monkeypatch):
    notifier = DesktopNotifier(DesktopNotifierConfig(urgency_threshold="HIGH"))
    notifier._notify_send_path = "synthetic-notify"
    monkeypatch.setattr(notifier, "_is_gui_available", lambda: True)
    spawn = AsyncMock(return_value=SimpleNamespace(communicate=AsyncMock(), returncode=0))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    assert await notifier.send(synthetic_alert()) is False
    spawn.assert_not_awaited()
    assert await notifier.send(synthetic_alert(Severity.HIGH)) is True
    assert spawn.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["send", "test"])
async def test_desktop_cancellation_reaps_subprocess(monkeypatch, operation):
    from unittest.mock import Mock
    started = asyncio.Event()
    async def block():
        started.set()
        await asyncio.Event().wait()
    proc = SimpleNamespace(communicate=block, returncode=None, kill=Mock(), wait=AsyncMock(return_value=-9))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", AsyncMock(return_value=proc))
    notifier = DesktopNotifier(DesktopNotifierConfig())
    notifier._notify_send_path = "synthetic-notify"
    monkeypatch.setattr(notifier, "_is_gui_available", lambda: True)
    task = asyncio.create_task(notifier.send(synthetic_alert()) if operation == "send" else notifier.test())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    proc.kill.assert_called_once()
    proc.wait.assert_awaited_once()
