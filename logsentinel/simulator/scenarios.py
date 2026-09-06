"""Simulated log scenarios for security attacks, system failures, and benign noise."""

from __future__ import annotations
from datetime import datetime, timezone
import random
from typing import List
from logsentinel.core.models import LogEntry, LogSourceType


def generate_ssh_bruteforce(ip: str = "198.51.100.42", count: int = 12) -> List[LogEntry]:
    """Generates a burst of SSH failed password attempts from an external IP."""
    users = ["root", "admin", "test", "ubuntu", "ina", "deploy"]
    entries = []
    base_port = 43210
    now = datetime.now(timezone.utc)

    for i in range(count):
        user = random.choice(users)
        port = base_port + i
        msg = f"Failed password for invalid user {user} from {ip} port {port} ssh2"
        if user in ("root", "admin"):
            msg = f"Failed password for {user} from {ip} port {port} ssh2"

        entries.append(LogEntry(
            source_type=LogSourceType.SIMULATION,
            source_name="simulation:ssh_bruteforce",
            service="sshd",
            message=msg,
            raw=f"Sep 05 12:00:{i:02d} omarchy sshd[{14000 + i}]: {msg}",
            priority=5,
            pid=14000 + i,
            hostname="omarchy",
            timestamp=now,
        ))
    return entries


def generate_sudo_violation(user: str = "guest", command: str = "/bin/cat /etc/shadow") -> List[LogEntry]:
    """Generates sudo privilege violation attempt."""
    now = datetime.now(timezone.utc)
    msg = f"{user} : user NOT in sudoers ; TTY=pts/2 ; PWD=/tmp ; USER=root ; COMMAND={command}"
    return [
        LogEntry(
            source_type=LogSourceType.SIMULATION,
            source_name="simulation:sudo_violation",
            service="sudo",
            message=msg,
            raw=f"Sep 05 12:05:10 omarchy sudo: {msg}",
            priority=4,
            pid=15201,
            hostname="omarchy",
            timestamp=now,
        )
    ]


def generate_oom_killer(process_name: str = "heavy_worker", pid: int = 28410) -> List[LogEntry]:
    """Generates kernel out of memory killer events."""
    now = datetime.now(timezone.utc)
    lines = [
        "kernel: [12345.678] oom-killer: gfp_mask=0x100cca(GFP_HIGHUSER_MOVABLE), order=0, oom_score_adj=0",
        f"kernel: [12345.679] Out of memory: Killed process {pid} ({process_name}) total-vm:8291040kB, anon-rss:6201400kB, file-rss:0kB, shmem-rss:0kB",
        f"systemd[1]: {process_name}.service: A process of this unit has been killed by the OOM killer.",
        f"systemd[1]: {process_name}.service: Main process exited, code=killed, status=9/KILL",
        f"systemd[1]: {process_name}.service: Failed with result 'oom-kill'.",
    ]
    entries = []
    for line in lines:
        entries.append(LogEntry(
            source_type=LogSourceType.SIMULATION,
            source_name="simulation:oom_killer",
            service="kernel" if "kernel" in line else "systemd",
            message=line,
            raw=line,
            priority=3,
            hostname="omarchy",
            timestamp=now,
        ))
    return entries


def generate_disk_full(mount_point: str = "/var/log") -> List[LogEntry]:
    """Generates filesystem no space left on device error logs."""
    now = datetime.now(timezone.utc)
    lines = [
        f"kernel: EXT4-fs error (device sda2): ext4_lookup:1795: inode #1234: comm rsyslogd: No space left on device",
        f"systemd[1]: Failed to write journal at {mount_point}: No space left on device",
        f"auditd[800]: Audit daemon failed to write log record: No space left on device",
    ]
    entries = []
    for line in lines:
        entries.append(LogEntry(
            source_type=LogSourceType.SIMULATION,
            source_name="simulation:disk_full",
            service="kernel" if line.startswith("kernel:") else ("auditd" if line.startswith("auditd[") else "systemd"),
            message=line,
            raw=line,
            priority=2,
            hostname="omarchy",
            timestamp=now,
        ))
    return entries


def generate_service_crash(service_name: str = "nginx") -> List[LogEntry]:
    """Generates service segfault and core dump logs."""
    now = datetime.now(timezone.utc)
    lines = [
        f"kernel: {service_name}[19200]: segfault at 0 ip 00007f31a2 sp 00007ffe error 4 in {service_name}[7f3100+a000]",
        f"systemd-coredump[19205]: Process 19200 ({service_name}) of user 33 dumped core.",
        f"systemd[1]: {service_name}.service: Main process exited, code=dumped, status=11/SEGV",
        f"systemd[1]: {service_name}.service: Failed with result 'core-dump'.",
    ]
    entries = []
    for line in lines:
        entries.append(LogEntry(
            source_type=LogSourceType.SIMULATION,
            source_name="simulation:service_crash",
            service="kernel" if line.startswith("kernel:") else ("systemd-coredump" if line.startswith("systemd-coredump[") else "systemd"),
            message=line,
            raw=line,
            priority=3,
            hostname="omarchy",
            timestamp=now,
        ))
    return entries


def generate_benign_noise() -> List[LogEntry]:
    """Generates harmless desktop or cron messages to test false-positive filtering."""
    now = datetime.now(timezone.utc)
    lines = [
        ("uwsm_hyprland.desktop", "Errors from xkbcomp are not fatal to the X server"),
        ("uwsm_hyprland.desktop", ">                   Using 0, ignoring 0"),
        ("CRON", "(root) CMD (/usr/lib/sysstat/sa1 1 1)"),
        ("systemd-logind", "New session 42 of user ina."),
    ]
    entries = []
    for svc, msg in lines:
        entries.append(LogEntry(
            source_type=LogSourceType.SIMULATION,
            source_name="simulation:benign_noise",
            service=svc,
            message=msg,
            raw=f"Sep 05 12:30:00 omarchy {svc}: {msg}",
            priority=6,
            hostname="omarchy",
            timestamp=now,
        ))
    return entries




def generate_thermal_overheat() -> List[LogEntry]:
    """Generates thermal throttling and critical hardware temperature logs."""
    now = datetime.now(timezone.utc)
    lines = [
        "kernel: [ 102.345678] thermal thermal_zone0: critical temperature reached (105 C), shutting down",
        "kernel: [ 102.345680] CPU0: Core temperature above threshold, cpu clock throttled (total events = 1420)",
        "kernel: [ 102.345682] mce: [Hardware Error]: Machine check events logged (processor thermal trip)",
    ]
    entries = []
    for line in lines:
        entries.append(LogEntry(
            source_type=LogSourceType.SIMULATION,
            source_name="simulation:thermal_overheat",
            service="kernel",
            message=line,
            raw=line,
            priority=1,
            hostname="omarchy",
            timestamp=now,
        ))
    return entries

SCENARIOS = {
    "thermal-overheat": generate_thermal_overheat,
    "ssh-bruteforce": generate_ssh_bruteforce,
    "sudo-violation": generate_sudo_violation,
    "oom-kill": generate_oom_killer,
    "disk-full": generate_disk_full,
    "service-crash": generate_service_crash,
    "benign-noise": generate_benign_noise,
}
