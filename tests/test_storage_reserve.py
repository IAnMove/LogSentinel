import shutil
from contextlib import contextmanager

import pytest

from helpers import machine_source
from logsentinel.portal.sender_safety import CaptureGate, SenderLimits
from logsentinel.portal.store import Store, dumps
from test_portal_telemetry import configured, sample

MiB = 1024**2


def free_disk(monkeypatch, free):
    monkeypatch.setattr(
        shutil, "disk_usage", lambda path: shutil._ntuple_diskusage(10**12, 10**12 - free, free)
    )


def set_reserve(store, mb):
    settings = store.settings().model_copy(update=dict(min_free_mb=mb))
    store.set_meta("settings", dumps(settings.model_dump()))


def test_the_reserve_is_applied_to_the_snapshot_taken_under_the_write_lock(client, monkeypatch):
    c, store = client
    _, source_id = machine_source(c)
    source = store.get("source", source_id)
    locked = {"now": False}
    original = Store.connect

    @contextmanager
    def connect(self):
        with original(self) as db:
            class Proxy:
                def execute(self, sql, *args, **kwargs):
                    if sql == "BEGIN IMMEDIATE":
                        locked["now"] = True
                    return db.execute(sql, *args, **kwargs)

                def executemany(self, *args, **kwargs):
                    return db.executemany(*args, **kwargs)

                def __getattr__(self, name):
                    return getattr(db, name)

            yield Proxy()

    def usage(self):
        return dict(
            allocated_bytes=0, reusable_bytes=0, used_bytes=0, quota_bytes=1000 * MiB,
            warning_bytes=800 * MiB, reserve_bytes=512 * MiB,
            disk_free_bytes=0 if locked["now"] else 10**12,
        )

    monkeypatch.setattr(Store, "connect", connect)
    monkeypatch.setattr(Store, "storage_usage", usage)
    with pytest.raises(OSError, match="free-space reserve"):
        store.ingest(source, [dict(origin="a", message="one fresh line")])
    assert store.events(limit=10) == []


def test_ingest_refuses_below_the_reserve_and_the_reserve_is_configurable(client, monkeypatch):
    c, store = client
    machine, source_id = machine_source(c)
    source = store.get("source", source_id)
    assert store.settings().min_free_mb == 512
    free_disk(monkeypatch, 400 * MiB)
    with pytest.raises(OSError, match="free-space reserve"):
        store.ingest(source, [dict(origin="a", message="one line")])
    set_reserve(store, 64)
    assert store.ingest(source, [dict(origin="a", message="one line")]) == 1


def test_the_health_check_warns_at_twice_the_reserve_and_is_critical_below_it(client, monkeypatch):
    c, store = client
    machine_source(c)

    def storage():
        return next(check for check in c.app.state.health.conditions() if check["key"] == "storage")

    free_disk(monkeypatch, 1500 * MiB)
    assert not storage()["bad"]
    free_disk(monkeypatch, 900 * MiB)
    check = storage()
    assert check["bad"] and check["severity"] == "HIGH"
    assert check["detail"]["reserve_bytes"] == 512 * MiB
    free_disk(monkeypatch, 400 * MiB)
    assert storage()["severity"] == "CRITICAL"
    set_reserve(store, 128)
    assert not storage()["bad"]


def test_a_metrics_sample_is_refused_below_the_reserve(client, monkeypatch):
    c, store = client
    machine, monitor = configured(c, store)
    free_disk(monkeypatch, 400 * MiB)
    with pytest.raises(OSError, match="free-space reserve"):
        monitor.receive(machine, sample())
    free_disk(monkeypatch, 1500 * MiB)
    assert monitor.receive(machine, sample())


def test_the_spool_takes_the_senders_own_reserve(tmp_path):
    store = Store(tmp_path)
    CaptureGate(store, SenderLimits(min_free_mb=64))
    assert store.settings().min_free_mb == 64
