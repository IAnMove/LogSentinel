"""Feedback and memory acquisition engine."""

from __future__ import annotations
import ipaddress
import re
from typing import Optional, Tuple
from logsentinel.core.models import Alert, MemoryRule, MemoryRuleType
from logsentinel.memory.store import MemoryStore


class FeedbackLearner:
    """Interprets user feedback and converts it into memory rules."""

    def __init__(self, store: MemoryStore):
        self.store = store

    def learn_from_text(
        self,
        text: str,
        rule_type: Optional[MemoryRuleType] = None,
        description: Optional[str] = None,
    ) -> MemoryRule:
        """Parse natural user instruction or explicit filter and persist it."""
        text = text.strip()

        # If rule type is not explicitly provided, infer the best rule type
        if rule_type is None:
            rule_type, clean_content = self._infer_rule_type(text)
        else:
            clean_content = text

        if not clean_content:
            raise ValueError("Memory rule must not be empty")
        if rule_type == MemoryRuleType.IP_ADDRESS:
            ipaddress.ip_network(clean_content, strict=False)
        elif rule_type == MemoryRuleType.PATTERN:
            try:
                re.compile(clean_content)
            except re.error as exc:
                raise ValueError("Invalid suppression regex") from exc

        rule = MemoryRule(
            rule_type=rule_type,
            content=clean_content,
            description=description or f"User defined rule: '{text}'",
        )
        self.store.add_rule(rule)
        self.store.record_feedback(alert_id=None, instruction=text, rule_id=rule.id)
        return rule

    def learn_from_alert_dismiss(
        self,
        alert: Alert,
        instruction: Optional[str] = None,
        create_permanent_rule: bool = True,
    ) -> Optional[MemoryRule]:
        """Dismiss an alert and optionally create a permanent suppression rule."""
        rule: Optional[MemoryRule] = None

        if create_permanent_rule:
            if instruction:
                rule = self.learn_from_text(
                    instruction,
                    description=f"Auto-learned from dismissed alert {alert.id} ({alert.verdict.title})",
                )
            elif alert.incident.entries and all(entry.message.strip() for entry in alert.incident.entries):
                # Model suggestions are untrusted regex. Dismissal authorizes only
                # these exact observed messages, not a synthesized generalization.
                messages = dict.fromkeys(entry.message for entry in alert.incident.entries)
                content = r"\A(?-i:" + "|".join(re.escape(message) for message in messages) + r")\Z"
                rule = MemoryRule(
                    rule_type=MemoryRuleType.PATTERN,
                    content=content,
                    description=f"Exact-message suppression for alert {alert.id}: {alert.verdict.title}",
                    metadata={"service": alert.incident.service, "origin": "dismiss_exact_messages"},
                )
                self.store.add_rule(rule)

        self.store.record_feedback(
            alert_id=alert.id,
            instruction=instruction or "Dismissed by user with permanent ignore rule",
            rule_id=rule.id if rule else None,
        )
        return rule

    def _infer_rule_type(self, text: str) -> Tuple[MemoryRuleType, str]:
        """Infer whether input is an IP, Service, Regex pattern, or Semantic instruction."""
        clean = text.strip()

        # Only a bare valid address/network or an explicit affirmative command.
        # Never discard negation, qualifiers, or surrounding natural language.
        candidate = re.sub(r"^(?:ignore|ignora)\s+", "", clean, flags=re.IGNORECASE)
        try:
            ipaddress.ip_network(candidate, strict=False)
        except ValueError:
            # An invalid address-looking token must not become a broad regex.
            if re.fullmatch(r"[0-9.]+(?:/[^\s]+)?", candidate) or re.fullmatch(r"[0-9A-Fa-f:]+(?:/[^\s]+)?", candidate) and ":" in candidate:
                return MemoryRuleType.SEMANTIC, clean
        else:
            return MemoryRuleType.IP_ADDRESS, candidate

        # 2. Explicit prefix rules
        svc_match = re.fullmatch(r"(?:service|servicio):\s*([a-zA-Z0-9_\-\.]+)", clean, re.IGNORECASE)
        if svc_match:
            return MemoryRuleType.SERVICE, svc_match.group(1).strip()

        if clean.startswith("regex:") or clean.startswith("pattern:"):
            return MemoryRuleType.PATTERN, clean.split(":", 1)[1].strip()

        # 3. Quoted strings: e.g. "Errors from xkbcomp..."
        if (clean.startswith('"') and clean.endswith('"')) or (clean.startswith("'") and clean.endswith("'")):
            return MemoryRuleType.PATTERN, clean[1:-1].strip()

        # 4. Regex characters present (.*, ^, $, [a-z], etc.)
        if any(c in clean for c in [".*", "\\d", "^", "$", "(?", "[0-9]"]):
            return MemoryRuleType.PATTERN, clean

        # 5. Single word token (e.g. "xkbcomp", "fail2ban", "dhcpcd")
        words = clean.split()
        if len(words) == 1:
            return MemoryRuleType.PATTERN, clean

        # 6. Natural language instructions with sentence indicators
        # Examples: "Ignora cuando el usuario ina se equivoca...", "No me avises de fallos de SSH..."
        return MemoryRuleType.SEMANTIC, clean
