"""Deterministic, bounded filters and outgoing-data redaction."""

import ipaddress
import json
import time
import regex
from logsentinel.memory.matcher import MemoryMatcher
from logsentinel.redact import redact, sanitize  # noqa: F401  (re-exported for the portal)


def protected_secrets(store):
    secrets = [
        store.settings().llm.api_key,
        store.meta("admin_token"),
        *json.loads(store.meta("retired_admin_tokens") or "[]"),
    ]
    for dest in store.objects("destination"):
        secrets.extend((dest.get("token"), dest.get("secret"), dest.get("url")))
    return tuple(value for value in secrets if value)


NOISE_PRESETS = (
    {
        "id": "systemd_timer_success",
        "name": "Temporizadores systemd correctos",
        "action": "exclude",
        "kind": "regex",
        "pattern": r"(?i)^(?:(?:Started|Stopped|Finished) [a-z0-9_.@:-]+\.timer\.?|[a-z0-9_.@:-]+\.timer: (?:Succeeded|Deactivated successfully)\.?)\Z",
        "note": "Solo líneas completas de inicio, parada o finalización correcta de un timer, sin texto adicional.",
    },
    {
        "id": "systemd_oneshot_success",
        "name": "Unidades oneshot correctas",
        "action": "exclude",
        "kind": "regex",
        "pattern": r"(?i)^[a-z0-9_.@:-]+\.service: Deactivated successfully\.?\Z",
        "note": "Solo la línea completa que indica desactivación correcta de una unidad. No demuestra que todo su trabajo haya sido correcto.",
    },
    {
        "id": "watchdog_lifecycle",
        "name": "Arranque y parada de watchdog",
        "action": "exclude",
        "kind": "regex",
        "pattern": r"(?i)^(?:Started|Stopped|Starting|Stopping) (?:llm-ram-watchdog|watchdog)\.service(?: - (?:LLM RAM watchdog|watchdog))?\.{0,3}\Z",
        "note": "Solo inicio o parada de watchdog.service o llm-ram-watchdog.service. Conserva mensajes con fallos o texto adicional.",
    },
)


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
    if rule["kind"] == "service":
        wanted = rule["pattern"].casefold()
        metadata = event.get("metadata") or {}
        return wanted in {
            str(event.get("service") or "").casefold(),
            str(metadata.get("systemd_unit") or "").casefold(),
            str(metadata.get("systemd_user_unit") or "").casefold(),
        }
    if rule["kind"] == "ip":
        return MemoryMatcher.matches_ip(event.get("message", ""), rule["pattern"])
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
