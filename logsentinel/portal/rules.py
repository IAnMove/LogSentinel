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
DISCORD_WEBHOOK = re.compile(
    r"(https://(?:[\w-]+\.)?discord(?:app)?\.com/api/webhooks/\d+/)[\w-]+",
    re.I,
)
SLACK_WEBHOOK = re.compile(r"(https://hooks\.slack\.com/services/)[A-Za-z0-9/]+", re.I)
AWS_KEY = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
SLACK_BOT = re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")
JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
PEM = re.compile(
    r"-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY-----[\s\S]{8,8000}?-----END [A-Z0-9 ]{0,40}PRIVATE KEY-----"
)


def protected_secrets(store):
    secrets = [
        store.settings().llm.api_key,
        store.meta("admin_token"),
        *json.loads(store.meta("retired_admin_tokens") or "[]"),
    ]
    for dest in store.objects("destination"):
        secrets.extend((dest.get("token"), dest.get("secret"), dest.get("url")))
    return tuple(value for value in secrets if value)


def redact(text, secrets=()):
    text = str(text)
    for secret in secrets:
        if secret and len(secret) > 3:
            text = text.replace(secret, "[REDACTED]")
    text = TELEGRAM_TOKEN.sub(lambda m: m[1] + "[REDACTED]", text)
    text = DISCORD_WEBHOOK.sub(lambda m: m[1] + "[REDACTED]", text)
    text = SLACK_WEBHOOK.sub(lambda m: m[1] + "[REDACTED]", text)
    text = AWS_KEY.sub("[REDACTED]", text)
    text = SLACK_BOT.sub("[REDACTED]", text)
    text = JWT.sub("[REDACTED]", text)
    text = PEM.sub("[REDACTED PRIVATE KEY]", text)
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
