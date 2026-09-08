import asyncio
import json
import time

import httpx
import pytest

from logsentinel.portal.analysis import Analyzer
from logsentinel.portal.chat_requests import ChatRequests
from logsentinel.portal.model_timing import estimate_model_time
from logsentinel.portal.store import Store


def request(id="synthetic-request-0001"):
    return dict(
        request_id=id,
        message="Is the finding supported?",
        machine_id="machine",
        problem_id="problem",
    )


def queue(tmp_path, execute):
    store = Store(tmp_path)
    analyzer = Analyzer(store)
    prepare = lambda body: ({}, {}, "", body["machine_id"], "", body["problem_id"])
    return ChatRequests(store, analyzer, prepare, execute)


@pytest.mark.asyncio
async def test_queue_waits_for_model_is_idempotent_and_finishes(tmp_path):
    calls = []
    entered, finish = asyncio.Event(), asyncio.Event()

    async def execute(body, request_id):
        calls.append(body)
        entered.set()
        await finish.wait()
        return {"answer": "Evidence is insufficient", "evidence_ids": []}

    q = queue(tmp_path, execute)
    await q.analyzer.lock.acquire()
    job = q.submit(request())
    assert job["status"] == "queued"
    assert q.submit(request())["id"] == job["id"]
    with pytest.raises(ValueError, match="pending question"):
        q.submit(request("synthetic-request-0002"))
    await asyncio.sleep(0)
    assert calls == []
    q.analyzer.lock.release()
    await asyncio.wait_for(entered.wait(), 1)
    assert q.store.get("chat_request", job["id"])["status"] == "running"
    assert q.analyzer.lock.locked()
    finish.set()
    await asyncio.gather(*list(q.tasks.values()))
    saved = q.store.get("chat_request", job["id"])
    assert saved["status"] == "completed"
    assert saved["finished"] >= saved["started"] >= saved["created"]
    assert saved["result"]["answer"] == "Evidence is insufficient"
    assert q.submit(request())["status"] == "completed"
    assert len(calls) == 1
    assert not q.analyzer.lock.locked()


@pytest.mark.asyncio
async def test_cancelled_queue_never_calls_model(tmp_path):
    calls = []

    async def execute(*args, **kwargs):
        calls.append(1)

    q = queue(tmp_path, execute)
    await q.analyzer.lock.acquire()
    job = q.submit(request())
    await asyncio.sleep(0)
    assert q.cancel(job["id"])["status"] == "cancelled"
    q.analyzer.lock.release()
    await q.close()
    assert calls == []
    assert q.store.get("chat_request", job["id"])["status"] == "cancelled"


@pytest.mark.asyncio
async def test_timeout_persists_failure_without_retry(tmp_path):
    calls = []

    async def execute(*args, **kwargs):
        calls.append(1)
        raise httpx.ReadTimeout("Model response did not arrive")

    q = queue(tmp_path, execute)
    job = q.submit(request())
    await asyncio.gather(*list(q.tasks.values()))
    saved = q.store.get("chat_request", job["id"])
    assert saved["status"] == "failed"
    assert saved["error_code"] == "model_timeout"
    assert saved["request"]["message"] == request()["message"]
    q.recover()
    await asyncio.sleep(0)
    assert calls == [1]


@pytest.mark.asyncio
async def test_restart_resumes_only_unsent_questions(tmp_path):
    calls = []

    async def execute(*args, **kwargs):
        calls.append(1)
        return {"answer": "Recovered"}

    q = queue(tmp_path, execute)
    await q.analyzer.lock.acquire()
    job = q.submit(request())
    await asyncio.sleep(0)
    await q.close()
    assert q.store.get("chat_request", job["id"])["status"] == "queued"
    q.analyzer.lock.release()
    recovered = queue(tmp_path, execute)
    recovered.recover()
    await asyncio.gather(*list(recovered.tasks.values()))
    assert calls == [1]
    recovered.save(job, status="running")
    recovered.recover()
    assert recovered.store.get("chat_request", job["id"])["status"] == "interrupted"
    assert calls == [1]


def test_latency_uses_matching_model_history_and_reports_missing_data(tmp_path):
    store = Store(tmp_path)
    assert estimate_model_time(store)["expected_seconds"] is None
    cfg = store.settings()
    with store.connect() as db:
        for i, duration in enumerate([80, 100, 120, 900]):
            detail = dict(
                provider=cfg.llm.provider,
                model=cfg.llm.model if i < 3 else "other-model",
            )
            db.execute(
                "INSERT INTO usage VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(i),
                    "",
                    "",
                    "[]",
                    "chat",
                    time.time(),
                    1,
                    1,
                    duration,
                    "ok",
                    json.dumps(detail),
                ),
            )
    estimate = estimate_model_time(store)
    assert estimate["expected_seconds"] == 100
    assert estimate["samples"] == 3
    assert estimate["basis"] == "same_task"
