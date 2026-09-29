"""Failures leave a traceback in the log, with secrets hidden and repeats suppressed."""

import asyncio
import io
import logging

import pytest

from logsentinel.portal import logs
from logsentinel.portal.logs import RedactingFormatter, configure, once_per, report
from helpers import until


@pytest.fixture(autouse=True)
def fresh():
    logs._last.clear()
    yield
    logs._last.clear()


@pytest.fixture
def stream():
    buffer = io.StringIO()
    root = logging.getLogger("logsentinel")
    saved = list(root.handlers)
    for handler in saved:
        root.removeHandler(handler)
    configure(stream=buffer)
    yield buffer
    for handler in list(root.handlers):
        root.removeHandler(handler)
    for handler in saved:
        root.addHandler(handler)


def test_a_failure_is_logged_with_its_traceback(stream):
    try:
        raise RuntimeError("database is locked")
    except RuntimeError as exc:
        report("analysis worker", exc)
    text = stream.getvalue()
    assert "analysis worker failed: RuntimeError" in text
    assert "Traceback" in text and "database is locked" in text


def test_secrets_are_hidden_in_the_message_and_the_traceback(stream):
    try:
        raise ValueError("upstream said password=hunter2 and Authorization: Bearer abcdef123456")
    except ValueError as exc:
        report("model triage", exc)
    text = stream.getvalue()
    assert "hunter2" not in text and "abcdef123456" not in text
    assert "[REDACTED]" in text


def test_a_failure_that_repeats_every_second_is_written_once(stream):
    for _ in range(50):
        report("collector", RuntimeError("same failure"))
    assert stream.getvalue().count("collector failed") == 1
    report("collector", RuntimeError("a different failure"))
    assert stream.getvalue().count("collector failed") == 2


def test_the_same_failure_is_written_again_after_the_interval(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(logs.time, "monotonic", lambda: clock[0])
    assert once_per("k", 300) and not once_per("k", 300)
    clock[0] += 301
    assert once_per("k", 300)


def test_the_set_of_remembered_failures_cannot_grow_without_bound():
    for i in range(2000):
        once_per(("worker", i))
    assert len(logs._last) <= 500


def test_delivery_errors_never_write_their_text_because_it_may_carry_a_destination_url(stream):
    report("delivery to hook", RuntimeError("POST https://hooks.example.invalid/T0/B0/token-secret failed"), trace=False)
    text = stream.getvalue()
    assert "delivery to hook failed: RuntimeError" in text
    assert "token-secret" not in text and "Traceback" not in text


def test_configuring_twice_does_not_duplicate_output(stream):
    configure(stream=stream)
    configure(stream=stream)
    report("x", RuntimeError("once"))
    assert stream.getvalue().count("x failed") == 1


def test_formatter_redacts_the_final_text():
    record = logging.LogRecord("logsentinel.portal", logging.ERROR, __file__, 1, "token=%s", ("supersecretvalue",), None)
    assert "supersecretvalue" not in RedactingFormatter("%(message)s").format(record)


@pytest.mark.asyncio
async def test_a_crashing_worker_step_is_logged_and_the_loop_survives(tmp_path, stream, monkeypatch):
    from logsentinel.portal.routes.context import build_context
    from logsentinel.portal.routes.workers import build_workers

    ctx = build_context(tmp_path, background=False)
    _, working, *_ = build_workers(ctx)

    async def broken():
        raise RuntimeError("synthetic monitor failure")

    monkeypatch.setattr(ctx.monitor, "tick", broken)
    task = asyncio.create_task(working())
    await until(lambda: "analysis worker failed" in stream.getvalue())
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert "analysis worker failed: RuntimeError" in stream.getvalue()
    assert ctx.store.meta("worker_error") == "synthetic monitor failure"
