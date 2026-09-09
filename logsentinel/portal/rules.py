"""Deterministic, bounded filters and outgoing-data redaction."""

import ipaddress
import json
import re
import time
import regex
from logsentinel.memory.matcher import MemoryMatcher

SECRET = re.compile(
    r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?|(?:api[ _-]?key|access[ _-]?key|token|password|secret)\s*[:=]\s*)[\"\']?[^\s,;\"\']+"
)
TELEGRAM_TOKEN = re.compile(r"(?i)(https?://api\.telegram\.org/bot)\d+:[A-Za-z0-9_-]+")


def protected_secrets(store):
    return (
        store.settings().llm.api_key,
        store.meta("admin_token"),
        *json.loads(store.meta("retired_admin_tokens") or "[]"),
    )


def redact(text, secrets=()):
    text = str(text)
    for secret in secrets:
        if secret and len(secret) > 3:
            text = text.replace(secret, "[REDACTED]")
    text = TELEGRAM_TOKEN.sub(lambda m: m[1] + "[REDACTED]", text)
    return SECRET.sub(lambda m: m[1] + "[REDACTED]", text)


def validate_rule(rule):
    if rule.kind == "regex":
        regex.compile(rule.pattern, regex.IGNORECASE)
    elif rule.kind == "ip":
        ipaddress.ip_network(rule.pattern, strict=False)
    return rule


def matches(rule, event, problem_id=""):
    if not rule.get("enabled", True):
        return False
    if rule.get("expires_at") and rule["expires_at"] < time.time():
        return False
    for field in ("machine_id", "source_id"):
        if rule.get(field) and rule[field] != event.get(field):
            return False
    if rule["kind"] == "problem":
        return rule["pattern"] == problem_id
    if rule["kind"] == "ip":
        return MemoryMatcher._matches_ip(event.get("message", ""), rule["pattern"])
    return bool(
        regex.search(
            rule["pattern"],
            event.get("message", ""),
            flags=regex.IGNORECASE,
            timeout=0.02,
        )
    )


def excluded(store, event, rules=None):
    for rule in store.objects("rule") if rules is None else rules:
        if rule["action"] != "exclude":
            continue
        try:
            if matches(rule, event):
                return True
        except (TimeoutError, regex.error):
            store.set_meta(
                "rule_error:" + rule["id"],
                "Filter evaluation failed; event was not excluded",
            )
    return False


def sanitize(value, secrets=()):
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, list):
        return [sanitize(v, secrets) for v in value]
    if isinstance(value, dict):
        return {k: sanitize(v, secrets) for k, v in value.items()}
    return value
