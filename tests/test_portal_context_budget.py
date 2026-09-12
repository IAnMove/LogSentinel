import json
import time

import httpx
import pytest

from logsentinel.portal.analysis import Analyzer, ContextBudgetExceeded, ReviewClient
from logsentinel.portal.batch_budget import input_ceiling, profile_key
from logsentinel.portal.context_budget import backend_key, token_policy
from logsentinel.portal.review_queue import ReviewQueue
from tests.test_portal_review_queue import queue, configure, ingest


def calibrate(store, cfg):
    store.set_meta(backend_key(cfg), json.dumps(dict(checked=time.time(), rejects_truncation=True, version="0.33.2")))
    for _ in range(3):
        store.record_usage("", "", [], "analysis", time.monotonic(), 2000, 30, "ok", dict(review_profile=profile_key(cfg), total_input_bytes=6000))


def test_only_matching_calibration_and_safe_backend_expand_input(queue):
    store, machine, source = queue
    cfg = configure(store, context_tokens=16384, input_budget=40000)
    cfg.llm.provider = "ollama"
    assert token_policy(store, cfg)["tokens_per_byte"] == 1
    calibrate(store, cfg)
    assert input_ceiling(cfg, machine, store) > input_ceiling(cfg, machine)
    other = cfg.model_copy(deep=True)
    other.llm.model = "different-model"
    assert token_policy(store, other)["tokens_per_byte"] == 1
    store.set_meta(backend_key(cfg), "{}")
    assert token_policy(store, cfg)["tokens_per_byte"] == 1


@pytest.mark.asyncio
async def test_large_request_is_rejected_without_truncation_and_forces_smaller_work(queue, monkeypatch):
    store, machine, source = queue
    cfg = configure(store, context_tokens=16384, input_budget=40000)
    cfg.llm.provider = "ollama"
    calibrate(store, cfg)
    requests = []
    def handler(request):
        if request.url.path.endswith("/api/version"):
            return httpx.Response(200, json={"version": "0.33.2"})
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(400, json={"error": "exceed_context_size_error"})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: original(**dict(kw, transport=httpx.MockTransport(handler))))
    with pytest.raises(ContextBudgetExceeded):
        await ReviewClient(store).call({"groups": [{"id": "g0", "message": "x" * 16000}]}, config=cfg)
    assert requests[0]["truncate"] is False and requests[0]["shift"] is False
    assert token_policy(store, cfg)["tokens_per_byte"] == 1


@pytest.mark.asyncio
async def test_fragment_context_split_keeps_complete_coverage_obligation(queue):
    store, machine, source = queue
    cfg = configure(store, input_budget=1200, adaptive_batching=False)
    store.ingest(source, [dict(origin="long", message="x" * 3000)])
    analyzer = Analyzer(store)
    worker = ReviewQueue(analyzer)
    work, _ = worker.prepare(machine, cfg, 0)
    async def rejected(*args, **kwargs):
        raise ContextBudgetExceeded("synthetic context rejection")
    analyzer.client.call = rejected
    assert await worker.execute(machine, work) == (1, 0)
    with store.connect() as db:
        rows = db.execute("SELECT start,end,covered FROM review_parts ORDER BY start").fetchall()
        assert db.execute("SELECT count(*) FROM review_parts WHERE job_id=?", (work[0],)).fetchone()[0] == 0
    assert rows[0]["start"] == 0 and rows[-1]["end"] == 3000
    assert all(a["end"] == b["start"] for a, b in zip(rows, rows[1:]))
    assert all(r["covered"] == 0 for r in rows)
