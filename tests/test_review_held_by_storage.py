"""While the central's storage is at its limit, the model review waits instead of writing more."""

import pytest

from logsentinel.portal.store import Store, dumps

MiB = 1024**2


def usage(monkeypatch, used, free=10**12):
    monkeypatch.setattr(
        Store,
        "storage_usage",
        lambda self: dict(
            allocated_bytes=used, reusable_bytes=0, used_bytes=used, quota_bytes=1000 * MiB,
            warning_bytes=800 * MiB, reserve_bytes=512 * MiB, disk_free_bytes=free,
        ),
    )


@pytest.mark.parametrize("used,free", [(1000 * MiB, 10**12), (100 * MiB, 100 * MiB)])
@pytest.mark.asyncio
async def test_the_review_waits_at_the_quota_or_the_reserve_and_resumes_after(client, monkeypatch, used, free):
    c, store = client
    monitor = c.app.state.monitor
    store.set_meta("settings", dumps(store.settings().model_copy(update=dict(enabled=True)).model_dump()))
    monitor.reschedule()
    cycles = []

    async def cycle():
        cycles.append(1)
        return {"calls": 1}

    monkeypatch.setattr(monitor.analyzer, "cycle", cycle)
    usage(monkeypatch, used, free)
    monitor.next_due = 0
    await monitor.tick()
    assert cycles == [] and monitor.state()["held"] == "storage"
    usage(monkeypatch, 100 * MiB)
    monitor.next_due = 0
    await monitor.tick()
    assert cycles == [1] and monitor.state()["held"] is None
