"""Fast prefiltering, noise reduction, and triage for raw log entries."""

from __future__ import annotations
import re
from typing import Optional, Tuple
from logsentinel.config import PrefilterConfig
from logsentinel.core.models import Category, LogEntry


class PreFilter:
    """Evaluates whether a log entry is worthy of analysis and derives signatures."""

    def __init__(self, config: PrefilterConfig):
        self.config = config
        self._sec_patterns = [re.compile(re.escape(k), re.IGNORECASE) for k in config.security_keywords]
        self._err_patterns = [re.compile(re.escape(k), re.IGNORECASE) for k in config.error_keywords]
        self._noise_patterns = [re.compile(re.escape(k), re.IGNORECASE) for k in config.noise_keywords]

    def should_analyze(self, entry: LogEntry) -> Tuple[bool, Optional[Category]]:
        """Determine if a log entry needs LLM analysis or can be safely skipped."""
        if not self.config.enabled:
            return True, Category.GENERAL

        raw_text = entry.message or entry.raw
        msg_lower = entry.message.lower()

        # Explicit security evidence wins over noise substrings in attacker data.
        for pattern in self._sec_patterns:
            if pattern.search(raw_text):
                return True, Category.SECURITY

        # Noise exceptions still precede generic words such as 'fatal'.
        for pattern in self._noise_patterns:
            if pattern.search(raw_text):
                return False, None

        # 2. Syslog priority check (Emergency, Alert, Critical, Error)
        if entry.priority is not None and entry.priority <= 3:
            for pattern in self._sec_patterns:
                if pattern.search(raw_text):
                    return True, Category.SECURITY
            return True, Category.SYSTEM_ERROR

        # 3. Security keyword check
        for pattern in self._sec_patterns:
            if pattern.search(raw_text):
                return True, Category.SECURITY

        # 4. Error keyword check
        for pattern in self._err_patterns:
            if pattern.search(raw_text):
                return True, Category.SYSTEM_ERROR

        # 5. Specific security service checks
        sec_services = {"sshd", "ssh", "sudo", "su", "fail2ban", "ufw", "audit", "pam"}
        if entry.service.lower() in sec_services:
            if any(term in msg_lower for term in ("failed", "invalid", "error", "session", "denied", "violation")):
                return True, Category.SECURITY

        return False, None

    @staticmethod
    def extract_signature(entry: LogEntry) -> str:
        """Create a normalized signature to group burst logs together into single incidents."""
        text = entry.message
        # Normalize authentication credential stuffing / brute force variations
        text = re.sub(r"invalid user \S+", "invalid user <USER>", text, flags=re.IGNORECASE)
        text = re.sub(r"Failed password for (?:invalid user )?\S+ from", "Failed password for <USER> from", text, flags=re.IGNORECASE)
        # Normalize PID / process id in messages
        text = re.sub(r"\[\d+\]", "[<PID>]", text)
        # Replace IPv4 addresses
        text = re.sub(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", "<IP>", text)
        # Replace port numbers
        text = re.sub(r"\bport \d+\b", "port <PORT>", text, flags=re.IGNORECASE)
        # Replace hex memory addresses
        text = re.sub(r"0x[0-9a-fA-F]+", "<ADDR>", text)
        # Replace numbers
        text = re.sub(r"\b\d+\b", "<NUM>", text)
        return f"{entry.service}:{text.strip()}"
