"""A batch refused by the budget check before any request is not a model call."""

import pytest

from logsentinel.portal.analysis import Analyzer, ContextBudgetExceeded, ReviewClient
from logsentinel.portal.models import Machine, Source
from logsentinel.portal.store import Store


@pytest.fixture
def queue(tmp_path):
    store = Store(tmp_path)
    machine = store.put("machine", Machine(name="A").model_dump())
    sid = store.put("source", Source(name="app", machine_id=machine, kind="push", enabled=True).model_dump())
    store.ingest(store.get("source", sid), [dict(origin="a", message="disk write failed", service="app")])
    return store


@pytest.mark.asyncio
async def test_a_payload_over_the_budget_records_no_usage(queue):
    store = queue
    settings = store.settings()
    settings.context_tokens = 2048
    settings.llm.max_tokens = 256
    store.set_meta("settings", settings.model_dump_json())
    client = ReviewClient(store)
    with pytest.raises(ContextBudgetExceeded):
        await client.call({"groups": [{"id": "g0", "message": "x" * 20_000}]})
    assert store.rows("usage") == [], "nothing was sent, so nothing is accounted"


@pytest.mark.asyncio
async def test_a_precheck_refusal_is_not_counted_as_a_call_of_the_cycle(queue):
    store = queue
    analyzer = Analyzer(store)

    async def refused_before_send(payload, **kwargs):
        raise ContextBudgetExceeded("Input exceeds the checked context budget")

    analyzer.client.call = refused_before_send
    result = await analyzer.cycle()
    assert result["calls"] == 0 and result["errors"] == 0
    assert analyzer.calls_started == 0
    assert [j["status"] for j in store.rows("jobs")] == ["cancelled"]
