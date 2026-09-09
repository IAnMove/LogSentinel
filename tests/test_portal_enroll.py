"""Enrollment hands out a credential once, to whoever holds a live code."""
import json
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from logsentinel.portal.app import create_app
from logsentinel.portal.enroll import fingerprint, issue_package, redeem
from logsentinel.portal.enrollment_client import claim, validate
from logsentinel.portal.ingest import create_ingest_app


@pytest.fixture(scope="module")
def certificate(tmp_path_factory):
    """A throwaway self-signed certificate; only its bytes matter to these tests."""
    folder = tmp_path_factory.mktemp("pki")
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
         "-subj", "/CN=sentinel.invalid",
         "-keyout", str(folder / "key.pem"), "-out", str(folder / "cert.pem")],
        check=True, capture_output=True,
    )
    return (folder / "cert.pem").read_text()


@pytest.fixture
def central(tmp_path):
    app = create_app(tmp_path, background=False)
    with TestClient(app, base_url="http://localhost") as panel:
        panel.post("/login", json={"token": app.state.store.meta("admin_token")})
        panel.headers["X-LogSentinel"] = "portal"
        machine = panel.post("/api/objects/machine", json={"name": "A"}).json()["id"]
        source = panel.post(
            "/api/objects/source",
            json={"name": "remote", "machine_id": machine, "kind": "push", "enabled": True},
        ).json()["id"]
        reception = TestClient(create_ingest_app(app.state.store), base_url="http://localhost")
        yield app.state.store, reception, source


def test_a_package_carries_a_code_and_never_the_credential(central, certificate):
    store, _, source = central
    package = issue_package(store, source, "https://central.invalid:8767", certificate)
    assert package["fingerprint"] == fingerprint(certificate)
    assert "token" not in json.dumps(package).lower().replace("push-token", "")
    assert package["expires"] > time.time()
    # The credential does not exist yet, so a leaked package cannot deliver logs.
    assert store.meta("push:" + source) is None


def test_an_https_package_refuses_to_ship_without_the_certificate(central):
    store, _, source = central
    with pytest.raises(ValueError, match="certificate"):
        issue_package(store, source, "https://central.invalid:8767")


def test_a_code_works_once(central):
    store, reception, source = central
    package = issue_package(store, source, "http://localhost")
    first = reception.post("/enroll", json={"source_id": source, "code": package["code"]})
    assert first.status_code == 200, first.text
    assert first.json()["token"]
    second = reception.post("/enroll", json={"source_id": source, "code": package["code"]})
    assert second.status_code == 401


def test_an_expired_code_is_refused(central):
    store, reception, source = central
    package = issue_package(store, source, "http://localhost", validity=60)
    pending = json.loads(store.meta("enroll:" + source))
    pending["expires"] = time.time() - 1
    store.set_meta("enroll:" + source, json.dumps(pending))
    assert reception.post(
        "/enroll", json={"source_id": source, "code": package["code"]}
    ).status_code == 401


def test_guessing_is_capped_and_reveals_no_source(central):
    store, reception, source = central
    issue_package(store, source, "http://localhost")
    for _ in range(12):
        assert reception.post(
            "/enroll", json={"source_id": source, "code": "wrong"}
        ).status_code == 401
    # Attempts are spent, so even the real code no longer works.
    with pytest.raises(KeyError, match="Too many"):
        redeem(store, source, "irrelevant")
    unknown = reception.post("/enroll", json={"source_id": "no-such-source", "code": "x"})
    assert unknown.status_code == 401
    assert "source" not in unknown.json()["detail"].lower()


def test_the_credential_earned_can_actually_deliver(central, tmp_path):
    store, reception, source = central
    package = issue_package(store, source, "http://localhost")
    result = claim(package, tmp_path / "spool", client=reception)
    token = (tmp_path / "spool" / "push-token").read_text().strip()
    assert (tmp_path / "spool" / "push-token").stat().st_mode & 0o777 == 0o600
    assert result["source_id"] == source
    delivered = reception.post(
        "/ingest/" + source,
        json={"events": [{"id": "e1", "raw": "synthetic enrolled line"}]},
        headers={"Authorization": "Bearer " + token},
    )
    assert delivered.status_code == 200, delivered.text


def test_a_package_whose_fingerprint_disagrees_with_its_certificate_is_rejected(certificate):
    package = {
        "logsentinel_enrollment": 1,
        "receiver": "https://central.invalid:8767",
        "source_id": "s1",
        "code": "c1",
        "ca_certificate": certificate,
        "fingerprint": "sha256:" + "0" * 64,
    }
    with pytest.raises(ValueError, match="fingerprint"):
        validate(package)


@pytest.mark.parametrize(
    "change, message",
    [
        ({"receiver": "http://central.invalid:8767"}, "plain http"),
        ({"receiver": "ftp://central.invalid"}, "http or https"),
        ({"logsentinel_enrollment": 99}, "another version"),
        ({"code": ""}, "missing"),
        ({"ca_certificate": "not a certificate"}, "readable PEM"),
    ],
)
def test_a_package_is_data_that_must_survive_checking(certificate, change, message):
    package = {
        "logsentinel_enrollment": 1,
        "receiver": "https://central.invalid:8767",
        "source_id": "s1",
        "code": "c1",
        "ca_certificate": certificate,
    }
    package.update(change)
    with pytest.raises(ValueError, match=message):
        validate(package)


def test_https_without_a_certificate_never_reaches_the_network(tmp_path):
    package = {
        "logsentinel_enrollment": 1,
        "receiver": "https://central.invalid:8767",
        "source_id": "s1",
        "code": "c1",
    }
    with pytest.raises(ValueError, match="must carry the certificate"):
        claim(package, tmp_path / "spool")
    assert not (tmp_path / "spool").exists()
