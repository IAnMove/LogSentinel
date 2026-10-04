"""A severe finding waiting for verification must still be shown if its job is cancelled."""

import pytest

from logsentinel.portal.analysis import Analyzer
from tests.test_portal_alert_reliability import add_destination, configure, deliveries, queue, triage_high  # noqa: F401


def change_the_model(store):
    settings = store.settings()
    settings.llm.model = "another-model"
    store.set_meta("settings", settings.model_dump_json())


def expire_the_evidence(store):
    with store.connect() as db:
        db.execute("DELETE FROM events")


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", [change_the_model, expire_the_evidence])
async def test_a_cancelled_verification_does_not_swallow_a_severe_finding(queue, cancel):  # noqa: F811
    store, machine, source = queue
    configure(store, max_calls=1)
    add_destination(store)
    store.ingest(source, [dict(origin="a", message="oom in worker", service="app")])
    analyzer = Analyzer(store)
    seen = []

    async def model(payload, **kwargs):
        seen.append(kwargs.get("kind"))
        if "groups" in payload:
            return triage_high(payload)
        raise AssertionError("verification must not run in this test")

    analyzer.client.call = model
    await analyzer.cycle()
    assert seen == ["analysis"], "triage ran and left its candidate waiting for verification"
    assert deliveries(store) == [], "nothing is sent before verification"
    assert store.rows("problems"), "the candidate is already visible as a problem"

    cancel(store)
    await analyzer.cycle()
    assert store.rows("jobs")[0]["status"] == "cancelled"
    sent = deliveries(store)
    assert len(sent) == 1 and sent[0]["severity"] == "HIGH"
    assert sent[0].get("verification_status") in ("preliminary", "unverified", "uncertain")
