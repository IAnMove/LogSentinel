"""Fixtures shared by the suite, and the environmental inputs no test may depend on."""

import pytest
from fastapi.testclient import TestClient

from logsentinel.portal.app import create_app


@pytest.fixture
def client(tmp_path):
    """A signed-in panel client and its store, over a fresh data directory."""
    app = create_app(tmp_path, background=False)
    with TestClient(app, base_url="http://localhost") as c:
        c.headers["X-LogSentinel"] = "portal"
        assert (
            c.post("/login", json={"token": app.state.store.meta("admin_token")}).status_code
            == 200
        )
        yield c, app.state.store


@pytest.fixture(autouse=True)
def idle_sender_disk(monkeypatch):
    """No test may depend on the host's live disk pressure.

    This ran opt-in per module, and each new sender test that forgot it failed
    only on a busy machine. It applies to every test now; those that exercise
    saturation and recovery (test_sender_backpressure) set their own readings
    afterwards, which replace these.
    """
    monkeypatch.setattr("logsentinel.portal.sender_safety.io_pressure", lambda: 0)
    monkeypatch.setattr("logsentinel.portal.sender_control.io_pressure", lambda: 0)
