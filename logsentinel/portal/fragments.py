"""Bounded slices of a redacted message, with durable references to its original."""

import hashlib

from .compaction import compact, public_group
from .rules import redact
from .store import dumps


def fragment_groups(event, budget, secrets=()):
    message = redact(event.get("message", ""), secrets)
    digest = hashlib.sha256(message.encode()).hexdigest()
    # Redact before cutting: a boundary must never split a credential into two
    # unrecognisable, unredacted halves. Offsets name this documented view.
    base = compact([dict(event, message="")], 1_000_000)[0][0]
    groups, start = [], 0
    while start < len(message):
        lo, hi, chosen = start + 1, len(message), None
        while lo <= hi:
            end = (lo + hi) // 2
            group = dict(base, message=message[start:end], fragment=dict(
                start=start, end=end, total=len(message), sha256=digest,
                offset_basis="redacted_message",
            ))
            if len(dumps([public_group(group)]).encode()) <= budget:
                chosen = group
                lo = end + 1
            else:
                hi = end - 1
        if chosen is None or len(groups) >= 4096:
            return []
        groups.append(chosen)
        start = chosen["fragment"]["end"]
    return groups
