"""Connect to checked numeric destinations while retaining the original TLS name."""

import socket
import time

import anyio
import httpcore
import httpx

from .models import _blocked_ip, METADATA_HOSTS


def destinations(host, answers):
    if host.rstrip(".").lower() in METADATA_HOSTS:
        raise httpcore.ConnectError("Cloud metadata destination is forbidden")
    addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
    if not addresses or any(_blocked_ip(ip) for ip in addresses):
        raise httpcore.ConnectError("Link-local or metadata destination is forbidden")
    return addresses


class CheckedAsyncBackend(httpcore.AnyIOBackend):
    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        try:
            with anyio.fail_after(timeout):
                answers = await anyio.getaddrinfo(host, port, type=socket.SOCK_STREAM)
                addresses = destinations(host, answers)
                failure = None
                for ip in addresses:
                    try:
                        # Only the validated numeric address reaches the connector.
                        # httpcore keeps the origin hostname for SNI/cert verification.
                        return await super().connect_tcp(ip, port, timeout, local_address, socket_options)
                    except httpcore.ConnectError as exc:
                        failure = exc
                raise failure
        except TimeoutError as exc:
            raise httpcore.ConnectTimeout("Destination lookup/connect timed out") from exc
        except OSError as exc:
            raise httpcore.ConnectError("Destination lookup failed") from exc


class CheckedSyncBackend(httpcore.SyncBackend):
    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        started = time.monotonic()
        try:
            answers = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise httpcore.ConnectError("Destination lookup failed") from exc
        addresses = destinations(host, answers)
        failure = None
        for ip in addresses:
            remaining = None if timeout is None else timeout - (time.monotonic() - started)
            if remaining is not None and remaining <= 0:
                raise httpcore.ConnectTimeout("Destination lookup/connect timed out")
            try:
                return super().connect_tcp(ip, port, remaining, local_address, socket_options)
            except httpcore.ConnectError as exc:
                failure = exc
        raise failure


class CheckedAsyncTransport(httpx.AsyncHTTPTransport):
    def __init__(self, verify=True):
        # HTTPX's adapter delegates requests/exception mapping/close to this pool.
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=verify, trust_env=False),
            network_backend=CheckedAsyncBackend(),
        )


class CheckedTransport(httpx.HTTPTransport):
    def __init__(self, verify=True):
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=verify, trust_env=False),
            network_backend=CheckedSyncBackend(),
        )
