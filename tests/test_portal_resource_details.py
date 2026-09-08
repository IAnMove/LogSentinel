import asyncio
from types import SimpleNamespace

from test_portal_api import client, machine_source
from logsentinel.portal.disk_info import DiskScans
from logsentinel.portal.telemetry_data import LinuxSampler, TelemetryConfig


def test_memory_threads_and_mounts(tmp_path, monkeypatch):
    (tmp_path / "self").mkdir()
    (tmp_path / "self/mountinfo").write_text(
        "1 0 8:1 / / rw - ext4 /dev/sda1 rw\n"
        "2 0 8:2 / /data rw - ext4 /dev/sdb1 rw\n"
        "3 0 0:1 / /proc rw - proc proc rw\n"
    )
    (tmp_path / "stat").write_text(
        "cpu 10 0 0 90 0 0 0 0\ncpu0 10 0 0 90 0 0 0 0\ncpu1 0 0 0 100 0 0 0 0\n"
    )
    (tmp_path / "meminfo").write_text(
        "MemTotal: 1000 kB\nMemAvailable: 600 kB\nMemFree: 100 kB\nShmem: 30 kB\nBuffers: 20 kB\nCached: 400 kB\nSReclaimable: 10 kB\nSwapTotal: 100 kB\nSwapFree: 60 kB\n"
    )
    (tmp_path / "loadavg").write_text("1 2 3 1/100 3")
    (tmp_path / "uptime").write_text("123 55")
    monkeypatch.setattr(
        "os.statvfs",
        lambda path: SimpleNamespace(
            f_blocks=100,
            f_bfree=30,
            f_bavail=20,
            f_frsize=1024,
            f_files=100,
            f_favail=90,
        ),
    )
    sampler = LinuxSampler(tmp_path)
    first = sampler.sample(["/"])
    v = first.values
    assert v["ram_used_bytes"] == 400 * 1024
    assert v["ram_free_bytes"] == 100 * 1024
    assert v["ram_shared_bytes"] == 30 * 1024
    assert v["ram_buff_cache_bytes"] == 430 * 1024
    assert v["disk_used_bytes:/data"] == 70 * 1024
    assert v["disk_available_bytes:/data"] == 20 * 1024
    assert {d.mount for d in first.disks} == {"/", "/data"}
    assert "cpu_thread_pct:0" not in v
    (tmp_path / "stat").write_text(
        "cpu 60 0 0 140 0 0 0 0\ncpu0 60 0 0 90 0 0 0 0\ncpu1 0 0 0 150 0 0 0 0\n"
    )
    v = sampler.sample(["/"]).values
    assert v["cpu_pct"] == 50
    assert v["cpu_thread_pct:0"] == 100
    assert v["cpu_thread_pct:1"] == 0
    sampler.discover_disks = False
    assert "disk_pct:/data" not in sampler.sample(["/"]).values


def test_disk_scan_is_explicit_local_and_does_not_follow_links(client, tmp_path):
    c, store = client
    machine, _ = machine_source(c)
    endpoint = f"/api/telemetry/{machine}/disk-info"
    assert c.post(endpoint, json={"path": str(tmp_path)}).status_code == 400
    c.post("/api/objects/machine", json={"id": machine, "kind": "local"})
    telemetry = c.app.state.telemetry
    telemetry.configure(
        machine,
        TelemetryConfig(
            mode="local", disk_paths=[str(tmp_path / "disk")], discover_disks=False
        ),
    )
    assert c.post(endpoint, json={"path": "/etc"}).status_code == 400
    disk = tmp_path / "disk"
    (disk / "large").mkdir(parents=True)
    (disk / "small").mkdir()
    (disk / "large/file").write_bytes(b"x" * 100000)
    (disk / "small/file").write_bytes(b"x" * 100)
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside/secret").write_bytes(b"x" * 200000)
    (disk / "link").symlink_to(tmp_path / "outside", target_is_directory=True)

    async def inspect():
        scans = DiskScans(store, telemetry)
        result = scans.start(machine, str(disk))
        await scans.tasks[result["id"]][1]
        return store.get("disk_scan", result["id"])

    result = asyncio.run(inspect())
    assert result["status"] == "completed"
    assert result["folders"][0]["path"] == str(disk / "large")
    assert not any(
        "link" in f["path"] or "secret" in f["path"] for f in result["folders"]
    )
    assert result["total_bytes"] >= sum(f["bytes"] for f in result["folders"])


def test_disk_scan_timeout_is_partial_and_stops_subprocess(client, monkeypatch):
    c, store = client
    machine, _ = machine_source(c)

    class Output:
        async def readuntil(self, separator):
            await asyncio.sleep(60)

    class Process:
        stdout = Output()
        returncode = None
        killed = False

        def kill(self):
            self.killed = True
            self.returncode = -9

        async def wait(self):
            return self.returncode

    process = Process()

    async def spawn(*args, **kwargs):
        assert args[0] == "du" and "-x" in args and "--null" in args
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    scans = DiskScans(store, c.app.state.telemetry)
    data = dict(
        machine_id=machine,
        path="/",
        limit_seconds=0.01,
        folders=[],
        total_bytes=None,
        partial=False,
        reason="",
    )
    asyncio.run(scans.run("bounded", data))
    result = store.get("disk_scan", "bounded")
    assert process.killed
    assert result["status"] == "partial" and result["reason"] == "time_limit"
