"""Helpers shared by test modules (fixtures live in conftest.py)."""


def machine_source(c):
    """A machine and an enabled push source, created through the API."""
    m = c.post("/api/objects/machine", json={"name": "A"}).json()["id"]
    r = c.post(
        "/api/objects/source",
        json={"name": "remote", "machine_id": m, "kind": "push", "enabled": True},
    )
    assert r.status_code == 200, r.text
    return m, r.json()["id"]


async def until(condition, timeout=5.0, step=0.01):
    """Wait for a condition instead of sleeping for a guess.

    A fixed sleep is too short on a loaded machine and wastes time on a fast
    one; this returns as soon as the condition holds and fails with a clear
    message if it never does."""
    import asyncio
    import time

    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "condition not reached in time"
        await asyncio.sleep(step)
