"""A sender writes down the build its central offers and reports what root did with it."""

import json
import time

import httpx
import pytest

from logsentinel.portal.sender import status
from logsentinel.portal.sender_control import REQUEST_FILE, SenderControl, UpgradeChannel
from logsentinel.portal.store import Store
from tests.test_portal_ingest import pair  # noqa: F401

COMMIT = "c" * 40
ACTIVE = {"version": 1, "capture_allowed": True, "delivery_allowed": True, "state": "active"}


class Central(httpx.AsyncBaseTransport):
    def __init__(self, control):
        self.control, self.posted = control, []

    async def handle_async_request(self, request):
        if request.url.path.startswith("/sender-control/"):
            return httpx.Response(200, json=self.control, request=request)
        self.posted.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True}, request=request)


async def heartbeat(tmp_path, control, enabled=True, state=None):
    store = Store(tmp_path / "spool")
    status(store, "capture", True)
    state_path = tmp_path / "upgrade-logs.json"
    if state is not None:
        state_path.write_text(json.dumps(state))
    transport = Central(control)
    async with httpx.AsyncClient(transport=transport, base_url="https://central.invalid") as client:
        control_client = SenderControl(
            store, client, "https://central.invalid", "src", {},
            UpgradeChannel(store, enabled=enabled, state_path=state_path),
        )
        await control_client.refresh()
    (payload,) = transport.posted
    request = store.directory / REQUEST_FILE
    return payload, (json.loads(request.read_text()) if request.exists() else None), control_client


@pytest.mark.asyncio
async def test_an_old_central_gets_no_upgrade_field_and_no_request_is_written(tmp_path):
    payload, request, control = await heartbeat(tmp_path, ACTIVE)
    assert "upgrade" not in payload and request is None
    assert control.capture_allowed and control.delivery_allowed


@pytest.mark.asyncio
async def test_a_new_central_without_an_offer_gets_the_policy_only(tmp_path):
    payload, request, _ = await heartbeat(tmp_path, dict(ACTIVE, upgrade=None))
    assert payload["upgrade"] == {"policy": "enabled", "offered": ""}
    assert request is None


@pytest.mark.asyncio
async def test_an_offer_is_written_for_root_and_echoed_with_roots_result(tmp_path):
    state = dict(status="installed", commit=COMMIT, version="1.1.0", observed=1700000000, message="ok\x00\n")
    payload, request, _ = await heartbeat(tmp_path, dict(ACTIVE, upgrade=dict(version="1.1.0", commit=COMMIT)), state=state)
    assert request["commit"] == COMMIT and request["version"] == "1.1.0"
    assert abs(request["seen"] - time.time()) < 60
    assert payload["upgrade"] == dict(
        policy="enabled", offered=COMMIT, status="installed", commit=COMMIT,
        version="1.1.0", observed=1700000000.0, message="ok",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("offer", [
    dict(version="1.1.0", commit="HEAD"),
    dict(version="1.1.0", commit="../" + "a" * 37),
    dict(version="1.1.0;rm", commit=COMMIT),
    dict(version="1.1.0"),
    "upgrade",
    42,
])
async def test_a_malformed_offer_is_ignored_and_the_lease_still_renews(tmp_path, offer):
    payload, request, control = await heartbeat(tmp_path, dict(ACTIVE, upgrade=offer))
    assert request is None and payload["upgrade"]["offered"] == ""
    assert control.capture_allowed and control.delivery_allowed


@pytest.mark.asyncio
async def test_a_host_that_disallows_remote_upgrades_never_writes_a_request(tmp_path):
    payload, request, _ = await heartbeat(tmp_path, dict(ACTIVE, upgrade=dict(version="1.1.0", commit=COMMIT)), enabled=False)
    assert request is None and payload["upgrade"] == {"policy": "disabled", "offered": COMMIT}


@pytest.mark.asyncio
async def test_a_withdrawn_offer_removes_the_request(tmp_path):
    store = Store(tmp_path / "spool")
    channel = UpgradeChannel(store, enabled=True)
    channel.accept(dict(version="1.1.0", commit=COMMIT))
    assert (store.directory / REQUEST_FILE).exists()
    first = (store.directory / REQUEST_FILE).read_text()
    channel.accept(dict(version="1.1.0", commit=COMMIT))
    assert (store.directory / REQUEST_FILE).read_text() == first  # same offer: not rewritten
    channel.accept(None)
    assert not (store.directory / REQUEST_FILE).exists()


def test_the_central_keeps_the_report_with_the_sender_health(pair):  # noqa: F811
    panel, reception, source, token, machine = pair
    report = dict(policy="enabled", offered=COMMIT, status="failed", commit=COMMIT, version="1.1.0", observed=1.0, message="sin espacio")
    sent = reception.post("/heartbeat/" + source, json={"ok": True, "pending": 0, "upgrade": report}, headers={"Authorization": "Bearer " + token})
    assert sent.status_code == 200, sent.text
    health = json.loads(panel.app.state.store.meta("health:" + source))
    assert health["sender"]["upgrade"] == report


def test_the_central_refuses_a_report_that_does_not_fit(pair):  # noqa: F811
    panel, reception, source, token, machine = pair
    for bad in (dict(policy="root"), dict(policy="enabled", commit="HEAD"), dict(policy="enabled", message="x" * 301)):
        sent = reception.post("/heartbeat/" + source, json={"ok": True, "pending": 0, "upgrade": bad}, headers={"Authorization": "Bearer " + token})
        assert sent.status_code == 400, bad
