"""A manual retry re-sends what failed; it does not send a delivered alert twice."""

import time

import pytest

from logsentinel.portal.models import Destination
from logsentinel.portal.store import dumps


def delivery(store, status):
    dest = store.put("destination", Destination(name="Local", kind="file", enabled=True).model_dump())
    now = time.time()
    with store.connect() as db:
        db.execute(
            "INSERT INTO deliveries VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("d-" + status, dest, "p1", dumps({"severity": "HIGH", "event_type": "problem.updated"}), status, 1, now, now, now, None),
        )
    return "d-" + status


@pytest.mark.parametrize("status", ["failed", "unknown", "muted"])
def test_a_delivery_that_did_not_arrive_can_be_retried(client, status):
    c, store = client
    id = delivery(store, status)
    assert c.post(f"/api/deliveries/{id}/retry").status_code == 200
    (row,) = [r for r in store.rows("deliveries") if r["id"] == id]
    assert row["status"] == "pending"


def test_a_delivered_notification_is_not_sent_again(client):
    c, store = client
    id = delivery(store, "delivered")
    answer = c.post(f"/api/deliveries/{id}/retry")
    assert answer.status_code == 409, answer.text
    (row,) = [r for r in store.rows("deliveries") if r["id"] == id]
    assert row["status"] == "delivered"
