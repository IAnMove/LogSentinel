"""The sender's side of enrollment: validate the package, then earn a credential.

The package arrives from outside, so nothing in it is trusted until checked. It
selects a receiver and a certificate authority; it never selects a file to read
or a command to run. The certificate is pinned before the first request, so a
machine answering at that address without the matching key gets nothing.
"""

from __future__ import annotations
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .enroll import PACKAGE_VERSION, fingerprint

REQUIRED = ("logsentinel_enrollment", "receiver", "source_id", "code")


def validate(package):
    """Check the package's shape and pinning before any of it reaches the network."""
    if not isinstance(package, dict):
        raise ValueError("The package must be a JSON object")
    missing = [key for key in REQUIRED if not package.get(key)]
    if missing:
        raise ValueError("The package is missing: " + ", ".join(missing))
    if package["logsentinel_enrollment"] != PACKAGE_VERSION:
        raise ValueError("This package was written for another version of LogSentinel")
    for key in ("receiver", "source_id", "code"):
        if not isinstance(package[key], str):
            raise ValueError(f"The package field {key} must be text")
    parts = urlsplit(package["receiver"])
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("The package receiver must be an http or https address")
    if parts.scheme == "http" and parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError(
            "Refusing to enroll over plain http; the credential would cross the network in the clear"
        )
    certificate = package.get("ca_certificate", "")
    if parts.scheme == "https" and not certificate:
        raise ValueError("An https package must carry the certificate to trust")
    if certificate:
        if not isinstance(certificate, str):
            raise ValueError("The package field ca_certificate must be text")
        try:
            actual = fingerprint(certificate)
        except (ValueError, TypeError):
            raise ValueError("The package certificate is not readable PEM")
        stated = package.get("fingerprint", "")
        if stated and stated != actual:
            raise ValueError(
                "The package fingerprint does not match its own certificate; do not use it"
            )
        return actual
    return ""


def claim(package, spool, client=None):
    """Redeem the package and write the credential where only this account reads it."""
    digest = validate(package)
    spool = Path(spool).expanduser()
    spool.mkdir(parents=True, exist_ok=True, mode=0o700)
    ca_path = ""
    verify = True
    if package.get("ca_certificate"):
        ca_path = spool / "receiver-ca.pem"
        _write_private(ca_path, package["ca_certificate"])
        verify = str(ca_path)
    receiver = package["receiver"].rstrip("/")
    owned = client is None
    client = client or httpx.Client(
        timeout=20, trust_env=False, follow_redirects=False, verify=verify
    )
    try:
        response = client.post(
            receiver + "/enroll",
            json={"source_id": package["source_id"], "code": package["code"]},
        )
    except httpx.HTTPError as failure:
        raise ValueError(f"Could not reach the receiver at {receiver}: {failure}")
    finally:
        if owned:
            client.close()
    if response.status_code == 401:
        raise ValueError("The receiver refused this code; it may be spent or expired")
    if response.status_code != 200:
        raise ValueError(f"The receiver answered {response.status_code}")
    token = response.json().get("token", "")
    if not isinstance(token, str) or not token:
        raise ValueError("The receiver returned no credential")
    token_path = spool / "push-token"
    _write_private(token_path, token + "\n")
    return {
        "source_id": package["source_id"],
        "receiver": receiver,
        "token_path": str(token_path),
        "ca_path": str(ca_path) if ca_path else "",
        "fingerprint": digest,
    }


def _write_private(path, text):
    """Create owner-only, and stay owner-only if the file already existed."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)
