"""Deterministic findings that do not wait for the model."""

from __future__ import annotations
import regex
import hashlib
from datetime import datetime

from .store import dumps

from .rules import excluded


SIGNALS = (
    {
        "id": "oom",
        "min": 1,
        "severity": "HIGH",
        "category": "resource",
        "pattern": r"(?i)out of memory|oom-kill|killed process \d+|Cannot allocate memory",
        "title": ("Proceso matado por falta de memoria", "Process killed: out of memory"),
        "summary": (
            "El kernel o el asignador reporta agotamiento de memoria.",
            "The kernel or allocator reported memory exhaustion.",
        ),
    },
    {
        "id": "disk_full",
        "min": 1,
        "severity": "HIGH",
        "category": "storage",
        "pattern": r"(?i)no space left on device|read-only file system|ENOSPC",
        "title": ("Disco lleno o sistema de archivos de solo lectura", "Disk full or read-only filesystem"),
        "summary": (
            "Una escritura falló por espacio o el volumen pasó a solo lectura.",
            "A write failed for space or the volume became read-only.",
        ),
    },
    {
        "id": "sudo_denied",
        "min": 1,
        "severity": "MEDIUM",
        "category": "authentication",
        "pattern": r"(?i)user NOT in sudoers|authentication failure;.+\bsudo\b|sudo:.*incorrect password attempts",
        "title": ("Autenticación sudo rechazada", "sudo authentication rejected"),
        "summary": (
            "Un intento de privilegio elevado fue rechazado. Puede ser un error o un abuso.",
            "A privilege-elevation attempt was rejected. It may be a mistake or abuse.",
        ),
    },
    {
        "id": "ssh_auth_failures",
        "min": 5,
        "window_seconds": 300,
        "severity": "HIGH",
        "category": "authentication",
        "pattern": r"(?i)failed password|authentication failure|invalid user|disconnected by authenticating user",
        "service": "sshd",
        "title": ("Varios rechazos de autenticación SSH", "Repeated SSH authentication rejections"),
        "summary": (
            "Hay varios fallos de SSH en una ventana de cinco minutos. No prueba un compromiso.",
            "Several SSH failures occurred within five minutes. That does not prove compromise.",
        ),
    },
)


def deterministic_signal(finding):
    if finding.get("detector"):
        return finding["detector"]
    # Recognise findings saved before detector identities were separated.
    for spec in SIGNALS:
        if finding.get("reasoning") == spec["id"] and finding.get("title") in spec["title"]:
            return spec["id"]
    if finding.get("reasoning") == "prompt-injection":
        return "prompt-injection"
    return None


def signal_batches(analyzer, limit, machine_id=None, events=None):
    """Use frozen originals when supplied; pending scans are only an early warning."""
    store = analyzer.store
    if events is not None:
        if not machine_id or any(e["machine_id"] != machine_id for e in events):
            raise ValueError("Signal evidence must belong to the selected machine")
        yield machine_id, events
        return
    for machine in store.objects("machine"):
        if store.monitoring_active(machine["id"]):
            pending = store.events(machine_id=machine["id"], status="pending", limit=limit)
            pending += store.events(machine_id=machine["id"], status="capacity", limit=limit)
            yield machine["id"], pending


def event_instant(event):
    try:
        value = datetime.fromisoformat(str(event.get("timestamp") or "").replace("Z", "+00:00"))
        if value.tzinfo is not None:
            return value.timestamp()
    except (ValueError, OverflowError):
        pass
    return event["received"]


def window_evidence(store, machine_id, spec, hits, rules):
    """Retain hit identities so model batches and restarts cannot reset a burst."""
    policy = hashlib.sha256(dumps([r for r in rules if r["action"] == "exclude"]).encode()).hexdigest()
    by_source = {}
    for event in hits:
        by_source.setdefault(event["source_id"], []).append(event)
    for source, incoming in by_source.items():
        instants = [event_instant(e) for e in incoming]
        width = spec["window_seconds"]
        with store.connect() as db:
            db.executemany(
                "INSERT OR REPLACE INTO signal_hits VALUES(?,?,?,?,?,?)",
                [(spec["id"], e["id"], machine_id, source, at, policy) for e, at in zip(incoming, instants)],
            )
            rows = db.execute(
                "SELECT event_id,instant FROM signal_hits WHERE signal=? AND machine_id=? AND source_id=? AND policy=? AND instant BETWEEN ? AND ? ORDER BY instant,event_id",
                (spec["id"], machine_id, source, policy, min(instants) - width, max(instants) + width),
            ).fetchall()
        incoming_ids = {e["id"] for e in incoming}
        left, new_in_window = 0, 0
        spans = []
        for right, row in enumerate(rows):
            new_in_window += row["event_id"] in incoming_ids
            while rows[left]["instant"] < row["instant"] - width:
                new_in_window -= rows[left]["event_id"] in incoming_ids
                left += 1
            if right - left + 1 >= spec["min"] and new_in_window:
                if spans and left <= spans[-1][1] + 1:
                    spans[-1] = (spans[-1][0], right)
                else:
                    spans.append((left, right))
        evidence = [rows[i]["event_id"] for start, end in spans for i in range(start, end + 1)]
        if evidence:
            originals = []
            for offset in range(0, len(evidence), 5000):
                originals.extend(store.events(ids=evidence[offset:offset + 5000], limit=5000))
            yield source, originals



def apply_signals(analyzer, limit=500, *, machine_id=None, events=None, notify=True):
    store = analyzer.store
    spanish = store.settings().language == "es"
    created = 0
    rules = store.objects("rule")
    for machine_id, events in signal_batches(analyzer, limit, machine_id, events):
        if not events:
            continue
        eligible = [e for e in events if not excluded(store, e, rules)]
        for spec in SIGNALS:
            hits = [
                e
                for e in eligible
                if regex.search(spec["pattern"], e.get("message") or "", timeout=0.02)
                and (
                    not spec.get("service")
                    or (e.get("service") or "").casefold()
                    == spec["service"].casefold()
                )
            ]
            batches = (
                window_evidence(store, machine_id, spec, hits, rules)
                if spec.get("window_seconds") and hits
                else [("", hits)]
            )
            for source_id, evidence in batches:
                if len(evidence) < spec["min"]:
                    continue
                save_signal(analyzer, machine_id, spec, evidence, spanish, source_id, notify=notify)
                created += 1
    return created


def save_signal(analyzer, machine_id, spec, hits, spanish, source_id="", *, notify=True):
    idx = 0 if spanish else 1
    analyzer.save_finding(
        machine_id,
        {
            "title": spec["title"][idx],
            "summary": spec["summary"][idx]
            + " "
            + ("Señal determinista; el modelo no la ha interpretado." if spanish else "Deterministic signal; the model has not interpreted it."),
            "severity": spec["severity"],
            "category": spec["category"],
            "evidence_ids": [e["id"] for e in hits[:100]],
            "reasoning": spec["id"],
            "next_steps": (
                "Comprueba los originales citados. No bloquees direcciones automáticamente."
                if spanish
                else "Inspect the cited originals. Do not automatically block addresses."
            ),
        },
        [e["id"] for e in hits],
        detector=spec["id"],
        notify=notify,
        notification_reason="historical_backfill" if not notify else None,
        fingerprint=(
            hashlib.sha256(dumps([machine_id, source_id, spec["id"]]).encode()).hexdigest()
            if spec.get("window_seconds") else None
        ),
    )
