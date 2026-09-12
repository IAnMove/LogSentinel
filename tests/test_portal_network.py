import socket
import ssl

import httpcore
import httpx
import pytest

from logsentinel.portal.models import check_url
from logsentinel.portal.network import CheckedAsyncBackend, CheckedSyncBackend, CheckedAsyncTransport, CheckedTransport


def answers(address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    return [(family, socket.SOCK_STREAM, 6, "", (address, 443))]


@pytest.mark.parametrize("host", ["2852039166", "0xa9fea9fe", "0251.0376.0251.0376", "169.254.43518", "169.254.169.254.", "[::ffff:169.254.169.254]"])
def test_alternative_metadata_literals_are_rejected(host):
    with pytest.raises(ValueError, match="metadata"):
        check_url("http://" + host + "/")


@pytest.mark.asyncio
@pytest.mark.parametrize("addresses", [["169.254.169.254"], ["127.0.0.1", "169.254.169.254"], ["fe80::1"], ["::ffff:169.254.169.254"]])
async def test_dns_metadata_aliases_are_blocked_before_async_connect(monkeypatch, addresses):
    async def resolve(*args, **kwargs):
        return [answer for address in addresses for answer in answers(address)]

    async def forbidden(*args, **kwargs):
        pytest.fail("Blocked addresses must never reach the TCP connector")

    monkeypatch.setattr("anyio.getaddrinfo", resolve)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", forbidden)
    async with httpx.AsyncClient(transport=CheckedAsyncTransport()) as client:
        with pytest.raises(httpx.ConnectError, match="metadata"):
            await client.post("https://alias.example/", content=b"synthetic credential")


def test_dns_metadata_alias_is_blocked_before_sync_connect(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: answers("169.254.169.254"))
    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", lambda *a, **kw: pytest.fail("blocked"))
    with httpx.Client(transport=CheckedTransport()) as client:
        with pytest.raises(httpx.ConnectError, match="metadata"):
            client.post("https://alias.example/", content=b"synthetic credential")


class Stream(httpcore.NetworkStream):
    def __init__(self):
        self.written = b""
        self.hostname = None

    def read(self, *args, **kwargs):
        return b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok"

    def write(self, buffer, **kwargs):
        self.written += buffer

    def start_tls(self, ssl_context, server_hostname=None, **kwargs):
        assert ssl_context.verify_mode == ssl.CERT_REQUIRED
        assert ssl_context.check_hostname
        self.hostname = server_hostname
        return self

    def close(self):
        pass

    def get_extra_info(self, info):
        return None


class AsyncStream(Stream, httpcore.AsyncNetworkStream):
    async def read(self, *args, **kwargs):
        return super().read(*args, **kwargs)

    async def write(self, *args, **kwargs):
        return super().write(*args, **kwargs)

    async def start_tls(self, *args, **kwargs):
        return super().start_tls(*args, **kwargs)

    async def aclose(self):
        pass


@pytest.mark.asyncio
async def test_async_connect_pins_checked_ip_and_preserves_host_and_tls_name(monkeypatch):
    stream = AsyncStream()
    lookups = []

    async def resolve(host, *args, **kwargs):
        lookups.append(host)
        return answers("192.168.1.20" if len(lookups) == 1 else "169.254.169.254")

    async def connect(self, host, *args, **kwargs):
        assert host == "192.168.1.20"
        return stream

    monkeypatch.setattr("anyio.getaddrinfo", resolve)
    monkeypatch.setattr(httpcore.AnyIOBackend, "connect_tcp", connect)
    async with httpx.AsyncClient(transport=CheckedAsyncTransport()) as client:
        assert (await client.get("https://receiver.example/test")).text == "ok"
    assert lookups == ["receiver.example"]
    assert stream.hostname == "receiver.example"
    assert b"Host: receiver.example" in stream.written


def test_sync_connect_pins_checked_ip_and_preserves_tls_name(monkeypatch):
    stream = Stream()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: answers("127.0.0.1"))

    def connect(self, host, *args, **kwargs):
        assert host == "127.0.0.1"
        return stream

    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp", connect)
    with httpx.Client(transport=CheckedTransport()) as client:
        assert client.get("https://receiver.example/test").text == "ok"
    assert stream.hostname == "receiver.example"
    assert b"Host: receiver.example" in stream.written
