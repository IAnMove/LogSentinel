"""A sender whose delivery is stuck says so in its heartbeat, and the central shows it."""

import json
import time

import httpx
import pytest

from logsentinel.portal.sender import status
from logsentinel.portal.sender_control import SenderControl
from logsentinel.portal.store import Store
from tests.test_portal_ingest import pair  # noqa: F401


class Capturing(httpx.AsyncBaseTransport):
    def __init__(self):
        self.posted = []

    async def handle_async_request(self, request):
        if request.url.path.startswith("/sender-control/"):
            return httpx.Response(200, json={"version": 1, "capture_allowed": True, "delivery_allowed": True, "state": "active"}, request=request)
        self.posted.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True}, request=request)


async def heartbeat_after(tmp_path, delivery_failed_for):
    store = Store(tmp_path / "spool")
    status(store, "capture", True)
    if delivery_failed_for is not None:
        status(store, "delivery", False, "Delivery failed", code="http_error", http_status=400)
        store._sender_status["delivery"]["checked"] -= delivery_failed_for
        store._sender_status["delivery"]["last_success"] = time.time() - delivery_failed_for
    transport = Capturing()
    async with httpx.AsyncClient(transport=transport, base_url="https://central.invalid") as client:
        await SenderControl(store, client, "https://central.invalid", "src", {}).refresh()
    (payload,) = transport.posted
    return payload


@pytest.mark.asyncio
async def test_a_delivery_stuck_for_a_while_turns_the_heartbeat_red(tmp_path):
    payload = await heartbeat_after(tmp_path, delivery_failed_for=1200)
    assert payload["ok"] is False
    assert payload["delivery_code"] == "delivery_blocked"


@pytest.mark.asyncio
async def test_a_fresh_delivery_failure_does_not_yet(tmp_path):
    payload = await heartbeat_after(tmp_path, delivery_failed_for=30)
    assert payload["ok"] is True
    assert payload["delivery_code"] == "http_error"


@pytest.mark.asyncio
async def test_a_healthy_sender_reports_ok_and_no_rejections(tmp_path):
    payload = await heartbeat_after(tmp_path, delivery_failed_for=None)
    assert payload["ok"] is True and payload["rejected"] == 0


def test_the_central_shows_a_blocked_delivery_as_a_source_error(pair):  # noqa: F811
    panel, reception, source, token, machine = pair
    headers = {"Authorization": "Bearer " + token}
    sent = reception.post("/heartbeat/" + source, json={"ok": False, "pending": 4200, "delivery_code": "delivery_blocked", "rejected": 2}, headers=headers)
    assert sent.status_code == 200, sent.text
    health = json.loads(panel.app.state.store.meta("health:" + source))
    assert health["status"] == "error" and "delivery_blocked" in health["error"]
    assert health["sender_rejected"] == 2 and health["sender_pending"] == 4200


def test_an_old_sender_without_the_new_fields_is_still_accepted(pair):  # noqa: F811
    panel, reception, source, token, machine = pair
    sent = reception.post("/heartbeat/" + source, json={"ok": True, "pending": 0}, headers={"Authorization": "Bearer " + token})
    assert sent.status_code == 200, sent.text
