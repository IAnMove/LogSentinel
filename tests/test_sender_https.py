"""Exercise enrollment, delivery and heartbeats over real, private-CA TLS."""

import asyncio
from contextlib import contextmanager
import json
import socket
import subprocess
import threading
import time

import pytest
import uvicorn

from logsentinel.portal.enroll import issue_package
from logsentinel.portal.enrollment_client import claim
from logsentinel.portal.forward import forward
from logsentinel.portal.ingest import create_ingest_app
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store

pytestmark = pytest.mark.usefixtures("idle_sender_disk")


def certificate(folder):
    folder.mkdir()
    cert, key = folder / "ca.pem", folder / "key.pem"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
        "-keyout", str(key), "-out", str(cert),
    ], check=True, capture_output=True)
    return cert, key


@contextmanager
def receiver(store, cert, key):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        create_ingest_app(store), ssl_certfile=str(cert), ssl_keyfile=str(key),
        log_level="error", access_log=False,
    ))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.01)
        assert server.started
        yield f"https://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()
        assert not thread.is_alive()


def test_enrolled_sender_uses_saved_ca_and_retains_queue_when_trust_fails(tmp_path):
    store = Store(tmp_path / "central")
    machine = store.put("machine", Machine(name="TLS test").model_dump())
    sid = store.put("source", Source(name="TLS logs", machine_id=machine, kind="push", enabled=True).model_dump())
    cert, key = certificate(tmp_path / "pki")
    other_ca, _ = certificate(tmp_path / "other-pki")
    spool = tmp_path / "spool with spaces"
    logfile = tmp_path / "app.log"
    logfile.write_text("first synthetic log\n")
    with receiver(store, cert, key) as url:
        package = issue_package(store, sid, url, cert.read_text())
        result = claim(package, spool)
        token = (spool / "push-token").read_text().strip()
        asyncio.run(forward(str(logfile), url, sid, token, spool, once=True))
        assert len(store.events()) == 1
        assert json.loads(store.meta("health:" + sid))["status"] == "ok"

        # A changed trust anchor must fail closed, without acknowledging the log.
        logfile.write_text("first synthetic log\nsecond synthetic log\n")
        (spool / "receiver-ca.pem").write_text(other_ca.read_text())
        with pytest.raises(RuntimeError, match="spool retained"):
            asyncio.run(forward(str(logfile), url, sid, token, spool, once=True))
        assert len(store.events()) == 1
        assert len(Store(spool).events(status="pending")) == 0  # No capture without valid authenticated control.
        (spool / "receiver-ca.pem").write_text(cert.read_text())
        asyncio.run(forward(str(logfile), url, sid, token, spool, once=True))
        assert len(store.events()) == 2
        assert not Store(spool).events(status="pending")
        assert result["ca_path"] == str(spool / "receiver-ca.pem")
