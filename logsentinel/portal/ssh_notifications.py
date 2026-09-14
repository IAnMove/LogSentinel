"""Recognise complete sshd rejection messages without inferring a successful ban."""

import ipaddress
import re


_USER = r"[^\s\x00-\x1f]{0,128}"
_PEER = r"(?P<ip>\S+) port (?P<port>\d{1,5})"
_PAM_FIELDS = rf"logname=[^\s\x00-\x1f]{{0,128}} uid=\d+ euid=\d+ tty=ssh ruser=[^\s\x00-\x1f]{{0,128}} rhost=(?P<ip>\S+)(?:[ \t]+user={_USER})?[ \t]*"
_FORMS = (
    ("invalid_user", rf"Invalid user {_USER} from {_PEER}"),
    ("failed_password", rf"Failed password for (?:invalid user )?{_USER} from {_PEER} ssh2"),
    ("failed_publickey", rf"Failed publickey for (?:invalid user )?{_USER} from {_PEER} ssh2"),
    ("failed_none", rf"Failed none for (?:invalid user )?{_USER} from {_PEER} ssh2"),
    ("preauth_closed", rf"Connection closed by (?:invalid user|authenticating user) {_USER} {_PEER} \[preauth\]"),
    ("preauth_disconnected", rf"Disconnected (?:from|by) (?:invalid user|authenticating user) {_USER} {_PEER} \[preauth\]"),
    ("pam_authentication_failure", rf"pam_unix\(sshd:auth\): authentication failure; {_PAM_FIELDS}"),
    ("pam_authentication_failures", rf"PAM [1-9]\d{{0,5}} more authentication failures?; {_PAM_FIELDS}"),
)
_PATTERNS = [(name, re.compile(pattern)) for name, pattern in _FORMS]


def rejection_form(event):
    """Accept only known full messages. Unknown, mixed and successful events fail open."""
    if (event.get("service") or "").casefold() != "sshd":
        return None
    message = event.get("message") or ""
    if not isinstance(message, str) or len(message) > 1024:
        return None
    repeated = re.fullmatch(r"message repeated [1-9]\d{0,5} times: \[ (.+)\]", message)
    if repeated:
        message = repeated[1]
    for name, pattern in _PATTERNS:
        match = pattern.fullmatch(message)
        if match:
            try:
                ipaddress.ip_address(match["ip"])
            except ValueError:
                return None
            port = match.groupdict().get("port")
            if port is None or 1 <= int(port) <= 65535:
                return name
    return None


def subject_for(events, ids):
    """Classify every supplied original, never a model title or a sample of evidence."""
    if not events or {e["id"] for e in events} != set(ids):
        return None
    sources = {e["source_id"] for e in events}
    if len(sources) != 1 or not all(rejection_form(e) for e in events):
        return None
    return next(iter(sources))
