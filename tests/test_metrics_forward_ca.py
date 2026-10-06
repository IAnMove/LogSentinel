"""metrics-forward trusts the receiver's pinned certificate authority when the spool holds one."""

import hashlib
import ssl
import subprocess

import httpx
import pytest

from logsentinel.portal import telemetry_forward
from logsentinel.portal.app import create_app
from logsentinel.portal.models import Machine
from logsentinel.portal.telemetry_data import LinuxSampler, MetricSample, TelemetryConfig
from logsentinel.portal.telemetry_forward import forward_metrics


@pytest.fixture
def receiver(tmp_path, monkeypatch):
    app = create_app(tmp_path / "receiver", background=False)
    store = app.state.store
    machine = store.put("machine", Machine(name="Remote").model_dump())
    app.state.telemetry.configure(machine, TelemetryConfig(enabled=True, mode="remote"))
    store.set_meta("telemetry_token:" + machine, hashlib.sha256(b"synthetic").hexdigest())
    monkeypatch.setattr(LinuxSampler, "sample", lambda self, paths: MetricSample(values={"cpu_pct": 5}))
    seen = []
    transport = httpx.ASGITransport(app=app)

    def recording(verify=True):
        seen.append(verify)
        return transport

    monkeypatch.setattr(telemetry_forward, "CheckedAsyncTransport", recording)
    return machine, seen


@pytest.fixture
def ca_pem(tmp_path):
    out = tmp_path / "ca.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1", "-subj", "/CN=central",
                    "-keyout", str(tmp_path / "k.pem"), "-out", str(out)], check=True, capture_output=True)
    return out.read_bytes()


@pytest.mark.asyncio
async def test_a_pinned_authority_in_the_spool_is_used(tmp_path, receiver, ca_pem):
    machine, seen = receiver
    spool = tmp_path / "spool"
    spool.mkdir()
    (spool / "receiver-ca.pem").write_bytes(ca_pem)
    await forward_metrics("http://localhost", machine, "synthetic", spool, once=True)
    assert len(seen) == 1 and isinstance(seen[0], ssl.SSLContext)


@pytest.mark.asyncio
async def test_without_a_pinned_authority_the_system_ones_are_used(tmp_path, receiver):
    machine, seen = receiver
    await forward_metrics("http://localhost", machine, "synthetic", tmp_path / "spool", once=True)
    assert seen == [True]
