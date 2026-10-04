"""Read Apache and nginx access-log lines (common and combined formats).

Every field of an access line is chosen by a stranger on the internet. The line
is therefore matched as a whole or not at all, every field has a length bound,
and nothing here is ever interpreted: a line that does not fit is simply not a
web request and the caller keeps it as plain text.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

MAX_LINE = 16384
WEB_SERVICE = "web-access"

# Fixed English abbreviations: Apache and nginx write these whatever the
# locale, and strptime("%b") would not read them under another one.
_MONTHS = {
    name: number
    for number, name in enumerate(
        ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"), 1
    )
}

# One character of a quoted field. A plain character excludes the backslash and
# the quote, an escape consumes the backslash and what follows it, so the two
# alternatives never overlap and a failed match cannot backtrack badly.
_Q = r'(?:[^"\\]|\\.)'
_LINE = re.compile(
    r"(?P<ip>[0-9A-Fa-f:.]{2,45}) \S{1,128} \S{1,128} "
    r"\[(?P<day>\d{2})/(?P<month>[A-Za-z]{3})/(?P<year>\d{4})"
    r":(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2}) (?P<zone>[+-]\d{4})\] "
    rf'"(?P<request>{_Q}{{0,8192}})" (?P<status>\d{{3}}) (?P<size>\d{{1,15}}|-)'
    # Combined format adds the referer and the agent; a proxy-aware format a
    # third quoted field. Anything after that, such as a request time, is
    # tolerated and ignored.
    rf'(?: "(?P<referer>{_Q}{{0,2048}})" "(?P<agent>{_Q}{{0,2048}})"'
    rf'(?: "(?P<forwarded>{_Q}{{0,512}})")?)?'
    r"(?: [^\n]{0,512})?",
    re.ASCII,
)
_REQUEST = re.compile(r"(?P<method>[A-Z]{3,10}) (?P<target>\S{1,8192})(?: (?P<protocol>HTTP/[0-9.]{1,5}))?", re.ASCII)

# What is kept in an event's metadata. The original line is always kept too.
FIELD_LIMITS = {"target": 2048, "referer": 512, "agent": 512, "forwarded_for": 256}


@dataclass(frozen=True)
class AccessRecord:
    ip: str
    time: datetime  # timezone-aware, UTC
    method: str  # empty when the request line was not a request
    target: str  # path and query exactly as the client sent them
    protocol: str
    status: int
    size: int | None
    referer: str
    agent: str
    forwarded_for: str  # as logged; a client can forge it, so it is never trusted

    def fields(self) -> dict:
        """JSON-safe, length-bounded view stored with the event."""
        return {
            "ip": self.ip,
            "method": self.method,
            "target": self.target[: FIELD_LIMITS["target"]],
            "protocol": self.protocol,
            "status": self.status,
            "size": self.size,
            "referer": self.referer[: FIELD_LIMITS["referer"]],
            "agent": self.agent[: FIELD_LIMITS["agent"]],
            "forwarded_for": self.forwarded_for[: FIELD_LIMITS["forwarded_for"]],
        }


def _instant(match):
    month = _MONTHS.get(match["month"])
    zone = match["zone"]
    hours, minutes = int(zone[1:3]), int(zone[3:5])
    if month is None or hours > 14 or minutes > 59:
        return None
    offset = timedelta(hours=hours, minutes=minutes)
    try:
        local = datetime(
            int(match["year"]),
            month,
            int(match["day"]),
            int(match["hour"]),
            int(match["minute"]),
            int(match["second"]),
            tzinfo=timezone(-offset if zone[0] == "-" else offset),
        )
    except ValueError:
        return None
    return local.astimezone(timezone.utc)


def parse_access_line(line: str) -> AccessRecord | None:
    """The request a line records, or None when it is not an access-log line."""
    line = line.rstrip("\r\n")
    if len(line) > MAX_LINE or '"' not in line or "[" not in line:
        return None
    match = _LINE.fullmatch(line)
    if match is None:
        return None
    try:
        address = ipaddress.ip_address(match["ip"])
    except ValueError:
        return None
    status = int(match["status"])
    when = _instant(match)
    if when is None or not 100 <= status <= 599:
        return None
    request = _REQUEST.fullmatch(match["request"])
    return AccessRecord(
        ip=str(getattr(address, "ipv4_mapped", None) or address),
        time=when,
        method=request["method"] if request else "",
        target=request["target"] if request else match["request"],
        protocol=(request["protocol"] or "") if request else "",
        status=status,
        size=None if match["size"] == "-" else int(match["size"]),
        referer=match["referer"] or "",
        agent=match["agent"] or "",
        forwarded_for=match["forwarded"] or "",
    )
