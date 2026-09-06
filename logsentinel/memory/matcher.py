"""Rule evaluation and memory matching for incidents."""

from __future__ import annotations
import ipaddress
import json
import re
from typing import List, Optional, Tuple
from logsentinel.core.models import Incident, MemoryRule, MemoryRuleType
from logsentinel.memory.store import MemoryStore


class MemoryMatcher:
    """Matches incidents against fast rules and formats semantic memory context."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def evaluate_fast_suppression(self, incident: Incident) -> Tuple[bool, Optional[MemoryRule]]:
        """Check if an incident matches any active PATTERN, SERVICE, or IP_ADDRESS rule.
        
        Returns (True, rule) if suppressed, otherwise (False, None).
        """
        active_rules = self.store.list_rules(active_only=True)

        for rule in active_rules:
            if "service" in rule.metadata and rule.metadata["service"] != incident.service:
                continue
            # 1. SERVICE rule
            if rule.rule_type == MemoryRuleType.SERVICE:
                if incident.service.lower() == rule.content.lower():
                    self.store.record_rule_hit(rule.id)
                    return True, rule

            # 2. PATTERN rule (Regex or Substring)
            elif rule.rule_type == MemoryRuleType.PATTERN:
                if not rule.content.strip():
                    continue
                try:
                    pattern = re.compile(rule.content, re.IGNORECASE)
                except re.error:
                    # Invalid rules are inert, never repaired into suppression.
                    continue

                if incident.entries and all(
                    pattern.search(entry.message)
                    for entry in incident.entries
                ):
                    self.store.record_rule_hit(rule.id)
                    return True, rule

            # 3. IP_ADDRESS rule
            elif rule.rule_type == MemoryRuleType.IP_ADDRESS:
                rule_ip = rule.content.strip()
                # A matching sample must not hide unrelated entries in the batch.
                if incident.entries and all(self._matches_ip(entry.message, rule_ip) for entry in incident.entries):
                    self.store.record_rule_hit(rule.id)
                    return True, rule

        return False, None

    def get_semantic_prompt_context(self, max_rules: int = 15) -> str:
        """Format active SEMANTIC rules for LLM prompt context."""
        semantic_rules = self.store.list_rules(active_only=True, rule_type=MemoryRuleType.SEMANTIC)
        if not semantic_rules:
            return ""

        return json.dumps([
            {"id": rule.id, "content": rule.content, "description": rule.description}
            for rule in semantic_rules[:max(0, max_rules)]
        ], ensure_ascii=True)

    @staticmethod
    def _matches_ip(text: str, target_ip_or_cidr: str) -> bool:
        """Check if an IP or CIDR is present in the text."""
        try:
            network = ipaddress.ip_network(target_ip_or_cidr, strict=False)
        except ValueError:
            return False

        # Parse complete address tokens; never fall back to substring matching.
        # IPv4 may carry a port; bracketed IPv6 naturally separates from its port.
        tokens = re.findall(r"(?<![\w.:])(?:[0-9A-Fa-f:.]+)(?![\w.:])", text)
        for token in tokens:
            candidate = token
            if candidate.count(":") == 1 and "." in candidate:
                candidate, port = candidate.rsplit(":", 1)
                if not port.isdigit():
                    continue
            try:
                address = ipaddress.ip_address(candidate)
            except ValueError:
                continue
            if address in network:
                return True
        return False
