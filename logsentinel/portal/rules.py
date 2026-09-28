"""Deterministic, bounded filters and outgoing-data redaction."""

import ipaddress
import json
import re
import time
import regex
from logsentinel.memory.matcher import MemoryMatcher

_KEYS = (
    r"(?:api|access|secret|private|auth|client|refresh|session|signing|encryption)[ _-]?(?:key|secret|token)"
    r"|token|password|passwd|passphrase|pwd|secret|credentials?|sessionid|session_id|phpsessid|jsessionid"
    r"|connect\.sid|csrf[_-]?token|xsrf-token"
)
_VALUE = r"""(?:"(?:[^"\\\r\n]|\\.)*"|'(?:[^'\\\r\n]|\\.)*'|[^\s,;"']+|["'][^\r\n]{0,200})"""
# key = value, key: value and "key": "value", also with a quoted value that has spaces.
SECRET = re.compile(r"(?i)((?:" + _KEYS + r")[\"']?\s*[:=]\s*)(" + _VALUE + ")")
AUTHORIZATION = re.compile(
    r"(?i)\b((?:proxy-)?authorization[\"']?\s*[:=]\s*[\"']?)(?:(bearer|basic|token|negotiate|ntlm|apikey)\s+)?([^\s,;\"']+)"
)
BEARER = re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}")
COOKIE = re.compile(r"(?i)\b((?:set-)?cookie[\"']?\s*[:=]\s*)[^\r\n]+")
URL_PASSWORD = re.compile(r"(\b[a-z][a-z0-9+.-]*://[^\s/:@]+:)[^\s/@]+(?=@)", re.I)
URL_TOKEN = re.compile(r"(\b[a-z][a-z0-9+.-]*://)[A-Za-z0-9_-]{20,}(?=@)", re.I)
CLI_SECRET = re.compile(
    r"(?i)(\s--?(?:password|passwd|pass|pwd|token|secret|passphrase|api[-_]?key|access[-_]?key|secret[-_]?key)(?:=|\s+))(\"[^\"]*\"|'[^']*'|\S+)"
)
SSHPASS = re.compile(r"(\bsshpass\b[^\n]{0,300}?\s-p\s*)(\"[^\"]*\"|'[^']*'|\S+)")
MYSQL_PASSWORD = re.compile(r"(\bmysql(?:dump|admin)?\b[^\n]{0,300}?\s-p)(?=\S)(\S+)")
CURL_USER = re.compile(r"(\bcurl\b[^\n]{0,300}?\s(?:-u|--user)[ =]?)([^\s:]+:)(\S+)")
TOKEN_PREFIXES = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{16,}"
    r"|sk-[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{30,}|npm_[A-Za-z0-9]{30,}|pypi-[A-Za-z0-9_-]{30,}"
    r"|ASIA[0-9A-Z]{16}|[sr]k_(?:live|test)_[A-Za-z0-9]{16,}|SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,})\b"
)
# Words that follow "token:" or "password:" in ordinary messages and are not secrets.
NOT_SECRET = frozenset(
    "expired invalid missing none null nil empty required revoked denied unknown true false "
    "rejected unset disabled enabled changed reset failed incorrect wrong ok".split()
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
PEM_TRUNCATED = re.compile(r"-----BEGIN [A-Z0-9 ]{0,40}PRIVATE KEY-----[A-Za-z0-9+/=\s]{0,8000}")


def protected_secrets(store):
    secrets = [
        store.settings().llm.api_key,
        store.meta("admin_token"),
        *json.loads(store.meta("retired_admin_tokens") or "[]"),
    ]
    for dest in store.objects("destination"):
        secrets.extend((dest.get("token"), dest.get("secret"), dest.get("url")))
    return tuple(value for value in secrets if value)


def _keep_scheme(match):
    scheme = match[2] + " " if match[2] else ""
    if match[3].startswith("[REDACTED"):
        return match[0]
    return match[1] + scheme + "[REDACTED]"


def _keep_unless_plain(match):
    key, value = match[1], match[2]
    if value.strip("\"'").rstrip(".").casefold() in NOT_SECRET or value.startswith(
        ("[REDACTED", '"[REDACTED', "'[REDACTED")
    ):
        return match[0]
    # sudo logs "PWD=/home/user": a working directory, not a password.
    if key.lower().startswith("pwd") and value.startswith("/"):
        return match[0]
    return key + "[REDACTED]"


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
    text = TOKEN_PREFIXES.sub("[REDACTED]", text)
    text = JWT.sub("[REDACTED]", text)
    text = PEM.sub("[REDACTED PRIVATE KEY]", text)
    text = PEM_TRUNCATED.sub("[REDACTED PRIVATE KEY]", text)
    text = COOKIE.sub(lambda m: m[1] + "[REDACTED]", text)
    text = AUTHORIZATION.sub(_keep_scheme, text)
    text = BEARER.sub(lambda m: m[1] + "[REDACTED]", text)
    text = URL_PASSWORD.sub(lambda m: m[1] + "[REDACTED]", text)
    text = URL_TOKEN.sub(lambda m: m[1] + "[REDACTED]", text)
    text = SSHPASS.sub(lambda m: m[1] + "[REDACTED]", text)
    text = MYSQL_PASSWORD.sub(lambda m: m[1] + "[REDACTED]", text)
    text = CURL_USER.sub(lambda m: m[1] + m[2] + "[REDACTED]", text)
    text = CLI_SECRET.sub(_keep_unless_plain, text)
    return SECRET.sub(_keep_unless_plain, text)


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
