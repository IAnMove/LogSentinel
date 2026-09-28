"""Incremental detection over originals, independent of model capacity and selection."""

import time

from .freshness import event_instant, happened_recently, live_cutoff
from .store import dumps

VERSION = 1


def scan_originals(analyzer, machine_id, events):
    from .signals import apply_signals
    from .injection import apply_injection_signals

    if any(e["machine_id"] != machine_id for e in events):
        raise ValueError("Signal evidence must belong to the selected machine")
    store = analyzer.store
    with analyzer.detector_lock:
        with store.connect() as db:
            done = {r[0] for r in db.execute(
                "SELECT event_id FROM signal_scans WHERE version=? AND event_id IN (SELECT value FROM json_each(?))",
                (VERSION, dumps([e["id"] for e in events])),
            )}
        pending = [e for e in events if e["id"] not in done]
        now = time.time()
        cutoff = live_cutoff(store.settings().interval_seconds, now)
        # Live events alert normally. Late ones alert only for severe signals
        # whose events are still recent, so a backlog cannot hide an OOM or an
        # attack; older backfill stays silent.
        for mode in (False, "severe", True):
            selected = [
                e for e in pending
                if (
                    True if e["received"] >= cutoff
                    else "severe" if happened_recently(event_instant(e), now)
                    else False
                ) == mode
            ]
            if not selected:
                continue
            apply_signals(analyzer, machine_id=machine_id, events=selected, notify=mode)
            apply_injection_signals(analyzer, machine_id=machine_id, events=selected, notify=mode is True)
            # Failed detection leaves the originals eligible. Finding appearances
            # and rolling hit identities make a replay safe after a crash.
            with store.connect() as db:
                db.executemany(
                    "INSERT OR REPLACE INTO signal_scans SELECT id,? FROM events WHERE id=?",
                    [(VERSION, e["id"]) for e in selected],
                )
        return len(pending)


def scan_signals(analyzer, limit=5000):
    store = analyzer.store
    count = 0
    errors = 0
    for machine in store.objects("machine"):
        if not store.monitoring_active(machine["id"]):
            continue
        with store.connect() as db:
            ids = [r[0] for r in db.execute(
                "SELECT e.id FROM events e LEFT JOIN signal_scans s ON s.event_id=e.id AND s.version=? "
                "WHERE e.machine_id=? AND s.event_id IS NULL AND e.status!='measured' "
                "AND e.source_id NOT IN (SELECT id FROM objects WHERE kind='source' AND json_extract(data,'$.kind') IN ('metrics','health')) "
                "ORDER BY e.received,e.rowid LIMIT ?",
                (VERSION, machine["id"], limit),
            )]
        try:
            if ids:
                count += scan_originals(analyzer, machine["id"], store.events(ids=ids, limit=limit))
            store.set_meta("detector_error:" + machine["id"], "")
        except Exception as exc:
            from .analysis import safe_error
            from .rules import protected_secrets
            errors += 1
            store.set_meta("detector_error:" + machine["id"], safe_error(exc, protected_secrets(store)))
    store.set_meta("detector_worker_error", "Deterministic detection failed for " + str(errors) + " machine(s); originals remain unchecked" if errors else "")
    return count
