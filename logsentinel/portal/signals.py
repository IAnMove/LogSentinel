"""Deterministic findings that do not wait for the model."""

from __future__ import annotations
import regex

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
        "severity": "HIGH",
        "category": "authentication",
        "pattern": r"(?i)failed password|authentication failure|invalid user|disconnected by authenticating user",
        "service": "sshd",
        "title": ("Varios rechazos de autenticación SSH", "Repeated SSH authentication rejections"),
        "summary": (
            "Hay varios fallos de SSH en el lote retenido. No prueba un compromiso.",
            "Several SSH failures are in the retained batch. That does not prove compromise.",
        ),
    },
)


def apply_signals(analyzer, limit=500):
    store = analyzer.store
    spanish = store.settings().language == "es"
    created = 0
    for machine in store.objects("machine"):
        if not store.monitoring_active(machine["id"]):
            continue
        events = store.events(machine_id=machine["id"], status="pending", limit=limit)
        events += store.events(machine_id=machine["id"], status="capacity", limit=limit)
        if not events:
            continue
        for spec in SIGNALS:
            hits = [
                e
                for e in events
                if not excluded(store, e)
                and regex.search(spec["pattern"], e.get("message") or "", timeout=0.02)
                and (
                    not spec.get("service")
                    or (e.get("service") or "").casefold()
                    == spec["service"].casefold()
                )
            ]
            if len(hits) < spec["min"]:
                continue
            idx = 0 if spanish else 1
            analyzer.save_finding(
                machine["id"],
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
                [e["id"] for e in hits[:100]],
            )
            created += 1
    return created
