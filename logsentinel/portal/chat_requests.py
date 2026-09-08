"""Observable chat requests sharing the model lock with automatic analysis."""

import asyncio
import json
import time
from typing import Literal

import httpx
from pydantic import Field

from .analysis import safe_error
from .models import Model
from .rules import sanitize
from .model_timing import estimate_model_time


ACTIVE = {"queued", "running"}


class ChatSubmission(Model):
    request_id: str = Field(min_length=16, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    message: str = Field(min_length=1, max_length=4000)
    machine_id: str = Field(default="", max_length=100)
    source_id: str = Field(default="", max_length=100)
    problem_id: str = Field(default="", max_length=100)
    language: Literal["en", "es"] = "en"


class ChatRequests:
    def __init__(self, store, analyzer, prepare, execute):
        self.store, self.analyzer = store, analyzer
        self.prepare, self.execute = prepare, execute
        self.tasks = {}

    def save(self, job, **changes):
        job.update(changes, updated=time.time())
        self.store.put(
            "chat_request", {k: v for k, v in job.items() if k != "id"}, job["id"]
        )
        return job

    def public(self, job):
        result = sanitize(job, (self.store.settings().llm.api_key,))
        result["server_time"] = time.time()
        estimate = (
            estimate_model_time(self.store)
            if job["status"] in ACTIVE
            else job.get("estimate", {})
        )
        result["estimate"] = estimate
        if job["status"] == "queued":
            result["queue_position"] = 1 + sum(
                other["status"] == "queued" and other["created"] < job["created"]
                for other in self.store.objects("chat_request")
            )
            active = json.loads(self.store.meta("model_active_call") or "{}")
            wait = 0
            if self.analyzer.lock.locked():
                current = estimate_model_time(
                    self.store, active.get("kind", "analysis")
                )
                typical = current["expected_seconds"]
                wait = (
                    None
                    if typical is None
                    else max(
                        0, typical - (time.time() - active.get("started", time.time()))
                    )
                )
                if self.analyzer.running and wait is not None:
                    # A cycle may still use the rest of its configured call allowance.
                    wait += (
                        max(
                            0,
                            self.store.settings().max_calls
                            - self.analyzer.calls_started,
                        )
                        * typical
                    )
            if estimate["expected_seconds"] is not None and wait is not None:
                wait += (result["queue_position"] - 1) * estimate["expected_seconds"]
            elif result["queue_position"] > 1:
                wait = None
            result["estimated_wait_seconds"] = round(wait) if wait is not None else None
            result["waiting_for_analysis"] = self.analyzer.running
        return result

    def submit(self, body):
        submission = ChatSubmission(**body)
        request = submission.model_dump(exclude={"request_id"})
        request = sanitize(request, (self.store.settings().llm.api_key,))
        id = "chatreq-" + submission.request_id
        existing = self.store.get("chat_request", id)
        if existing:
            if existing["request"] != request:
                raise ValueError("Request ID already belongs to another question")
            return self.public(existing)
        # Validate the selected machine, finding and context before queueing.
        _, _, _, machine, _, problem = self.prepare(request)
        jobs = self.store.objects("chat_request")
        active = [j for j in jobs if j["status"] in ACTIVE]
        if len(active) >= 10:
            raise ValueError("Chat queue is full; wait for an existing request")
        if any(
            j["machine_id"] == machine and j["problem_id"] == problem for j in active
        ):
            raise ValueError(
                "This conversation already has a pending question; check its status"
            )
        cfg = self.store.settings()
        job = dict(
            id=id,
            client_request_id=submission.request_id,
            request=request,
            machine_id=machine,
            problem_id=problem,
            status="queued",
            created=time.time(),
            started=None,
            finished=None,
            error=None,
            error_code=None,
            model=cfg.llm.model,
            timeout_seconds=cfg.llm.timeout_seconds,
            estimate=estimate_model_time(self.store),
        )
        self.save(job)
        # Keep bounded status history; completed conversations have their own ledger.
        terminal = sorted(
            (j for j in jobs if j["status"] not in ACTIVE), key=lambda j: j["created"]
        )
        for old in terminal[:-199]:
            self.store.delete("chat_request", old["id"])
        self.start(job["id"])
        return self.public(job)

    def start(self, id):
        if id not in self.tasks:
            task = asyncio.create_task(self.run(id))
            self.tasks[id] = task
            task.add_done_callback(lambda done: self.tasks.pop(id, None))

    async def run(self, id):
        job = self.store.get("chat_request", id)
        try:
            # Awaiting the fair shared lock reserves a turn after the current
            # analysis cycle, rather than repeatedly losing to the scheduler.
            async with self.analyzer.lock:
                job = self.store.get("chat_request", id)
                if not job or job["status"] != "queued":
                    return
                cfg = self.store.settings()
                self.save(
                    job,
                    status="running",
                    started=time.time(),
                    model=cfg.llm.model,
                    timeout_seconds=cfg.llm.timeout_seconds,
                    estimate=estimate_model_time(self.store),
                )
                result = await asyncio.wait_for(
                    self.execute(job["request"], request_id=id),
                    timeout=cfg.llm.timeout_seconds + 5,
                )
                self.save(job, status="completed", finished=time.time(), result=result)
        except asyncio.CancelledError:
            current = self.store.get("chat_request", id)
            if current and current["status"] == "running":
                self.save(
                    current,
                    status="interrupted",
                    finished=time.time(),
                    error_code="interrupted",
                    error="The portal stopped during this request. No automatic resend was made.",
                )
            raise
        except Exception as exc:
            timeout = isinstance(
                exc, (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException)
            )
            self.save(
                job,
                status="failed",
                finished=time.time(),
                error_code="model_timeout" if timeout else "model_error",
                error=safe_error(exc, (self.store.settings().llm.api_key,)),
            )

    def cancel(self, id):
        job = self.store.get("chat_request", id)
        if not job:
            raise KeyError(id)
        if job["status"] != "queued":
            raise ValueError(
                "Only a queued question can be cancelled; check its current status"
            )
        self.save(job, status="cancelled", finished=time.time())
        if id in self.tasks:
            self.tasks[id].cancel()
        return self.public(job)

    def recover(self):
        replies = {
            c.get("request_id"): c
            for c in self.store.objects("chat")
            if c.get("request_id")
        }
        for job in self.store.objects("chat_request"):
            if job["status"] == "running":
                if job["id"] in replies:
                    self.save(
                        job,
                        status="completed",
                        finished=time.time(),
                        result=replies[job["id"]]["response"],
                    )
                else:
                    self.save(
                        job,
                        status="interrupted",
                        finished=time.time(),
                        error_code="interrupted",
                        error="The portal restarted during this request. No automatic resend was made.",
                    )
            elif job["status"] == "queued":
                self.start(job["id"])

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
