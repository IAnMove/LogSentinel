"""Simulation generators produce synthetic data only."""
from logsentinel.simulator.scenarios import generate_oom_killer, generate_disk_full, generate_service_crash


def test_oom_uses_requested_process_identity():
    entries = generate_oom_killer("synthetic-worker", 123)
    killed = next(e for e in entries if "Killed process" in e.message)
    assert "Killed process 123 (synthetic-worker)" in killed.message


def test_disk_full_uses_requested_mount_and_correct_service():
    entries = generate_disk_full("/synthetic/mount")
    assert any("/synthetic/mount" in e.message for e in entries)
    assert next(e for e in entries if e.message.startswith("auditd")).service == "auditd"


def test_service_crash_attributes_coredump_to_its_reporter():
    entries = generate_service_crash("synthetic-worker")
    assert next(e for e in entries if e.message.startswith("systemd-coredump")).service == "systemd-coredump"
