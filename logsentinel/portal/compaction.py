"""Versioned, loss-accounted grouping of exact messages and known log formats."""

import hashlib
import json
import re
from datetime import datetime, timezone
import math

from .rules import redact
from .store import dumps

VERSION = "routine-dates-v1"
DATE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?" r"(?:Z|[+-]\d{2}:?\d{2})?\b"
)
LOGGING = re.compile(
    r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}[,.]\d+ "
    r"\[INFO\] (?P<logger>apscheduler\.executors\.default|httpx): (?P<body>[^\n]+)$"
)


def unit_for(event):
    metadata = event.get("metadata") or {}
    unit = metadata.get("systemd_user_unit") or metadata.get("systemd_unit")
    # Older journal entries retained the unit only in their immutable original.
    if not unit and str(event.get("source_type", "")).lower() == "journald":
        try:
            raw = json.loads(event.get("raw", ""))
            unit = raw.get("_SYSTEMD_USER_UNIT") or raw.get("_SYSTEMD_UNIT")
        except (ValueError, TypeError, AttributeError):
            pass
    return unit if isinstance(unit, str) else ""


def representation(event):
    message = event.get("message", "")
    unit = unit_for(event)
    match = LOGGING.fullmatch(message)
    known = False
    if match and unit and event.get("priority") in (None, 6):
        body = match["body"]
        if match["logger"] == "apscheduler.executors.default":
            known = bool(
                re.fullmatch(r'Running job "[^\n]+" \(scheduled at [^\n]+\)', body)
                or re.fullmatch(r'Job "[^\n]+" executed successfully', body)
            )
        else:
            known = bool(
                re.fullmatch(
                    r'HTTP Request: [A-Z]+ \S+ "HTTP/[\d.]+ 2\d\d [^"\n]+"', body
                )
            )
    template = message
    if known:
        template = DATE.sub("<time>", message, count=1)
        if match["logger"] == "apscheduler.executors.default":
            template = re.sub(
                r"(next run at: |scheduled at )" + DATE.pattern,
                lambda m: m[1] + "<time>",
                template,
            )
    # Dates alone are variable. Job names, intervals, URLs, addresses, status
    # codes, paths and identities remain part of the key, even after redaction.
    key = (
        event["source_id"],
        event.get("service", ""),
        unit,
        event.get("priority"),
        template,
    )
    return key, redact(template), unit, VERSION if known else "exact-v1"


def public_group(group):
    return {
        k: v for k, v in group.items() if k not in ("event_ids", "identity", "_times")
    }


def compact(events, budget):
    grouped = {}
    for event in events:
        key, template, unit, normalizer = representation(event)
        if key not in grouped:
            group = dict(
                id=event["id"],
                source_id=event["source_id"],
                service=event.get("service", "unknown"),
                priority=event.get("priority"),
                message=template,
                count=0,
                first=event.get("timestamp"),
                last=event.get("timestamp"),
                event_ids=[],
                identity=hashlib.sha256(dumps(key).encode()).hexdigest(),
            )
            if normalizer != "exact-v1":
                group.update(normalizer=normalizer, unit=unit, examples=[], _times=[])
            elif unit:
                group["unit"] = unit
            grouped[key] = group
        group = grouped[key]
        group["count"] += 1
        group["last"] = event.get("timestamp")
        group["event_ids"].append(event["id"])
        if "examples" in group:
            try:
                instant = datetime.fromisoformat(
                    event.get("timestamp", "").replace("Z", "+00:00")
                )
                if instant.tzinfo is not None:
                    group["_times"].append(instant.timestamp())
            except (ValueError, TypeError):
                pass
            example = dict(id=event["id"], message=redact(event.get("message", "")))
            if len(group["examples"]) < 2:
                group["examples"].append(example)
            else:
                group["examples"][-1] = example
    # Pack complete groups after counts/examples are final, so their growth
    # cannot exceed a previously measured request budget.
    admitted, selected, omitted = [], [], []
    used = 2
    for group in grouped.values():
        times = group.pop("_times", [])
        if times:
            # Keep bursts visible instead of flattening the whole window into
            # one average. At most 60 bins; zeros preserve quiet periods.
            width = max(60, math.ceil((max(times) - min(times) + 1) / 59 / 60) * 60)
            start = math.floor(min(times) / width) * width
            bins = [0] * (int((max(times) - start) // width) + 1)
            for instant in times:
                bins[int((instant - start) // width)] += 1
            group["frequency"] = dict(start=start, bin_seconds=width, counts=bins)
            group["first"] = datetime.fromtimestamp(
                min(times), tz=timezone.utc
            ).isoformat()
            group["last"] = datetime.fromtimestamp(
                max(times), tz=timezone.utc
            ).isoformat()
        cost = len(dumps(public_group(group)).encode()) + bool(admitted)
        if used + cost <= budget:
            admitted.append(group)
            selected.extend(group["event_ids"])
            used += cost
        else:
            omitted.extend(group["event_ids"])
    return admitted, selected, omitted
