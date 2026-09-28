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
import re
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
# the endpoint and filling the log with attempts. It is counted per client
# address: the source id is not secret, so a shared counter would let anyone
# who has seen it spend the ten attempts and burn the code of a real sender.
MAX_ATTEMPTS = 10
TRACKED_CLIENTS = 50


def fingerprint(certificate_pem):
    """SHA-256 over the certificate's DER form, the value openssl and browsers show."""
    return "sha256:" + hashlib.sha256(
        ssl.PEM_cert_to_DER_cert(certificate_pem)
    ).hexdigest()


def normalize_fingerprint(text):
    """Accept sha256:ab12..., SHA256:AB:12:... or bare hex, as tools print them."""
    value = str(text).strip().lower().removeprefix("sha256:")
    value = value.replace(":", "").replace(" ", "")
    if not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("A SHA-256 fingerprint has 64 hexadecimal digits")
    return "sha256:" + value


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


def redeem(store, source_id, code, client=""):
    """Exchange a valid code for a fresh source token, consuming the code."""
    raw = store.meta("enroll:" + source_id)
    if not raw:
        raise KeyError("No enrollment is open for this source")
    pending = json.loads(raw)
    if pending["expires"] < time.time():
        store.set_meta("enroll:" + source_id, "")
        raise KeyError("This enrollment expired; issue a new package")
    failures = pending.setdefault("failures", {})
    if failures.get(client, 0) >= MAX_ATTEMPTS:
        raise KeyError("Too many failed attempts from this address; try again from the sender or issue a new package")
    if not hmac.compare_digest(
        hashlib.sha256(code.encode()).hexdigest(), pending["code"]
    ):
        pending["attempts"] += 1
        if client not in failures and len(failures) >= TRACKED_CLIENTS:
            # Forget the oldest address so the record stays bounded; an address
            # that has not failed yet always starts with its full allowance.
            failures.pop(next(iter(failures)))
        failures[client] = failures.get(client, 0) + 1
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
            token = redeem(
                store,
                body["source_id"],
                body["code"],
                request.client.host if request.client else "",
            )
        except KeyError:
            raise HTTPException(401, "Enrollment refused")
        return {"token": token, "source_id": body["source_id"]}
