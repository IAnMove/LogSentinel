"""Explicit environmental inputs for sender protocol tests."""

import pytest


@pytest.fixture
def idle_sender_disk(monkeypatch):
    """Protocol tests should not depend on the CI host's live disk pressure.

    Saturation and recovery are exercised separately in test_sender_backpressure.
    Keep this opt-in so those tests retain control of their pressure readings.
    """
    monkeypatch.setattr("logsentinel.portal.sender_safety.io_pressure", lambda: 0)
    monkeypatch.setattr("logsentinel.portal.sender_control.io_pressure", lambda: 0)
