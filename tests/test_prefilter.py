"""Unit tests for prefiltering and signature extraction."""

from logsentinel.config import PrefilterConfig
from logsentinel.core.models import Category, LogEntry
from logsentinel.core.prefilter import PreFilter


def test_prefilter_noise_detection():
    config = PrefilterConfig(enabled=True)
    prefilter = PreFilter(config)

    entry = LogEntry(
        service="uwsm_hyprland.desktop",
        message="Errors from xkbcomp are not fatal to the X server",
        raw="Errors from xkbcomp are not fatal to the X server",
    )
    should_analyze, _ = prefilter.should_analyze(entry)
    assert not should_analyze


def test_prefilter_security_detection():
    config = PrefilterConfig(enabled=True)
    prefilter = PreFilter(config)

    entry = LogEntry(
        service="sshd",
        message="Failed password for root from 192.168.1.100 port 22 ssh2",
        raw="Failed password for root from 192.168.1.100 port 22 ssh2",
        priority=5,
    )
    should_analyze, cat = prefilter.should_analyze(entry)
    assert should_analyze
    assert cat == Category.SECURITY


def test_prefilter_hardware_error_detection():
    config = PrefilterConfig(enabled=True)
    prefilter = PreFilter(config)

    entry = LogEntry(
        service="kernel",
        message="thermal thermal_zone0: critical temperature reached (105 C), shutting down",
        raw="thermal thermal_zone0: critical temperature reached (105 C), shutting down",
        priority=1,
    )
    should_analyze, cat = prefilter.should_analyze(entry)
    assert should_analyze
    assert cat == Category.SYSTEM_ERROR


def test_signature_normalization():
    e1 = LogEntry(
        service="sshd",
        message="Failed password for invalid user alice from 10.0.0.1 port 54321 ssh2",
        raw="raw1",
    )
    e2 = LogEntry(
        service="sshd",
        message="Failed password for invalid user bob from 10.0.0.2 port 54322 ssh2",
        raw="raw2",
    )

    sig1 = PreFilter.extract_signature(e1)
    sig2 = PreFilter.extract_signature(e2)

    assert sig1 == sig2
    assert "<USER>" in sig1
    assert "<IP>" in sig1
    assert "<PORT>" in sig1
