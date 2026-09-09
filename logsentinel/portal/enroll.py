"""One-time enrollment: how a sender learns the receiver and earns its credential.

The package is data, never a script. It names the receiver, pins the certificate
authority the sender must trust, and carries a single-use code that expires. The
credential itself is never written into the package, so a copy left behind on a
USB stick or in a chat log stops being useful once it is redeemed or expires.
"""

from __future__ import annotations
import hashlib
import hmac
import json
import secrets
import ssl
import time

from fastapi import HTTPException, Request

from .models import check_url

PACKAGE_VERSION = 1
# Long enough to walk a package over to a machine, short enough that a stale copy
# is worthless. Redeeming it immediately invalidates it regardless.
DEFAULT_VALIDITY = 3600
# A 256-bit code is not guessable; this only stops a client from grinding against
# the endpoint and filling the log with attempts.
MAX_ATTEMPTS = 10


def fingerprint(certificate_pem):
    """SHA-256 over the certificate's DER form, the value openssl and browsers show."""
    return "sha256:" + hashlib.sha256(
        ssl.PEM_cert_to_DER_cert(certificate_pem)
    ).hexdigest()


def issue_package(store, source_id, receiver, certificate_pem="", validity=DEFAULT_VALIDITY):
    """Mint a package for one push source, replacing any code it already had."""
    check_url(receiver)
    source = store.get("source", source_id)
    if not source or source["kind"] != "push":
        raise ValueError("Select a push source")
    if certificate_pem:
        # Fail here rather than on the sender, where the operator cannot see why.
        fingerprint(certificate_pem)
    elif receiver.startswith("https://"):
        raise ValueError("An https receiver needs the certificate the sender must trust")
    code = secrets.token_urlsafe(32)
    store.set_meta(
        "enroll:" + source_id,
        json.dumps(
            {
                "code": hashlib.sha256(code.encode()).hexdigest(),
                "expires": time.time() + validity,
                "attempts": 0,
            }
        ),
    )
    store.audit("issue_enrollment", source_id)
    package = {
        "logsentinel_enrollment": PACKAGE_VERSION,
        "receiver": receiver.rstrip("/"),
        "source_id": source_id,
        "source_name": source["name"],
        "code": code,
        "expires": int(time.time() + validity),
    }
    if certificate_pem:
        package["ca_certificate"] = certificate_pem
        package["fingerprint"] = fingerprint(certificate_pem)
    return package


def redeem(store, source_id, code):
    """Exchange a valid code for a fresh source token, consuming the code."""
    raw = store.meta("enroll:" + source_id)
    if not raw:
        raise KeyError("No enrollment is open for this source")
    pending = json.loads(raw)
    if pending["expires"] < time.time():
        store.set_meta("enroll:" + source_id, "")
        raise KeyError("This enrollment expired; issue a new package")
    if pending["attempts"] >= MAX_ATTEMPTS:
        raise KeyError("Too many failed attempts; issue a new package")
    if not hmac.compare_digest(
        hashlib.sha256(code.encode()).hexdigest(), pending["code"]
    ):
        pending["attempts"] += 1
        store.set_meta("enroll:" + source_id, json.dumps(pending))
        raise KeyError("Enrollment code rejected")
    token = secrets.token_urlsafe(32)
    store.set_meta("push:" + source_id, hashlib.sha256(token.encode()).hexdigest())
    # Single use: the package is spent the moment it works.
    store.set_meta("enroll:" + source_id, "")
    store.audit("redeem_enrollment", source_id)
    return token


def register_enrollment(app, store):
    """Attach the sender-facing exchange."""

    @app.post("/enroll")
    async def enroll(request: Request):
        body = await request.json()
        if (
            not isinstance(body, dict)
            or not isinstance(body.get("source_id"), str)
            or not isinstance(body.get("code"), str)
            or not 1 <= len(body["source_id"]) <= 200
            or not 1 <= len(body["code"]) <= 200
        ):
            raise HTTPException(400, "Send source_id and code")
        source = store.get("source", body["source_id"])
        if not source or source["kind"] != "push":
            # Same answer as a wrong code: enrollment must not enumerate sources.
            raise HTTPException(401, "Enrollment refused")
        try:
            token = redeem(store, body["source_id"], body["code"])
        except KeyError:
            raise HTTPException(401, "Enrollment refused")
        return {"token": token, "source_id": body["source_id"]}
