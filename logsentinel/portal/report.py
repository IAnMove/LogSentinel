"""The daily report: one message a day saying what happened on each machine.

Built from the tables, without a model: problems that appeared or recurred,
checks that are failing, and from the brain what was worked on, what changed
in what is installed, and the notes agents left. It is meant to replace reading
a stream of single alerts, and to be the reminder of where work was done.
"""

from __future__ import annotations

import time
from datetime import datetime

from .store import dumps, uid

SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW")
TEXT = {
    "en": dict(
        title="LogSentinel daily report", period="Last 24 hours, to", quiet="Nothing to report.",
        problems="Problems", new="new", recurring="recurring", failing="Failing checks",
        worked="Worked on", commands="commands", changes="Installed changes", notes="Agent notes",
        more="more", open="open in total", ignored="ignored",
        added="added", removed="removed", changed="changed",
    ),
    "es": dict(
        title="Resumen diario de LogSentinel", period="Últimas 24 horas, hasta", quiet="Nada que contar.",
        problems="Problemas", new="nuevos", recurring="repetidos", failing="Comprobaciones fallando",
        worked="Se trabajó en", commands="órdenes", changes="Cambios en lo instalado", notes="Notas de agentes",
        more="más", open="abiertos en total", ignored="ignorados",
        added="añadido", removed="eliminado", changed="cambiado",
    ),
}


def build(store, brain, health=None, now=None, language=None):
    """The report as text, and whether it has anything in it."""
    now = time.time() if now is None else now
    since = now - 86400
    words = TEXT["es" if (language or store.settings().language) == "es" else "en"]
    lines = [words["title"], words["period"] + " " + datetime.fromtimestamp(now).strftime("%Y-%m-%d %H:%M")]
    anything = False
    failing: dict = {}
    if health is not None:
        for check in health.state().get("checks", []):
            if check.get("bad") and check.get("alert", True):
                failing.setdefault(check.get("machine_id", ""), []).append(check["title"])
    for machine in store.objects("machine"):
        id = machine["id"]
        section = []
        with store.connect() as db:
            rows = db.execute(
                "SELECT title,severity,count,first_seen FROM problems WHERE machine_id=? AND status='open' AND last_seen>=? "
                "ORDER BY CASE severity WHEN 'CRITICAL' THEN 0 WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END,last_seen DESC",
                (id, since),
            ).fetchall()
            totals = dict(
                db.execute(
                    "SELECT status,count(*) FROM problems WHERE machine_id=? GROUP BY status", (id,)
                ).fetchall()
            )
        if rows:
            by = {s: sum(r["severity"] == s for r in rows) for s in SEVERITIES}
            new = sum(r["first_seen"] >= since for r in rows)
            section.append(
                "  %s: %s (%d %s, %d %s; %d %s, %d %s)"
                % (
                    words["problems"],
                    ", ".join("%d %s" % (n, s) for s, n in by.items() if n),
                    new, words["new"], len(rows) - new, words["recurring"],
                    totals.get("open", 0), words["open"], totals.get("ignored", 0), words["ignored"],
                )
            )
            important = [r for r in rows if r["severity"] in ("CRITICAL", "HIGH")][:5]
            for row in important:
                section.append("    - [%s] %s (x%d)" % (row["severity"], row["title"], row["count"]))
            rest = sum(r["severity"] in ("CRITICAL", "HIGH") for r in rows) - len(important)
            if rest > 0:
                section.append("    - +%d %s" % (rest, words["more"]))
        if failing.get(id):
            section.append("  %s: %s" % (words["failing"], "; ".join(sorted(set(failing[id])))))
        projects = brain.data.projects(1, id, 8)
        if projects:
            section.append(
                "  %s: %s"
                % (
                    words["worked"],
                    ", ".join("%s (%d %s)" % (p["label"], p["commands"], words["commands"]) for p in projects),
                )
            )
        changes = brain.data.changes(id, 1, 200)
        if changes:
            shown = [
                "%s %s %s" % (words[c["action"]], c["item"], c["after"] or c["before"]) for c in changes[:6]
            ]
            extra = len(changes) - len(shown)
            section.append(
                "  %s: %s%s" % (words["changes"], "; ".join(shown), " (+%d %s)" % (extra, words["more"]) if extra > 0 else "")
            )
        notes = brain.data.notes(id, "", "", 1, 5)
        if notes:
            section.append("  " + words["notes"] + ":")
            for note in notes:
                section.append("    - %s, %s: %s" % (note["agent"], note["project"] or note["cwd"], note["text"][:300]))
        if section:
            anything = True
            lines += ["", machine["name"]] + section
    if not anything:
        lines += ["", words["quiet"]]
    return "\n".join(lines), anything


def due(store, now=None):
    """Whether today's report should go out now (server's local time)."""
    cfg = store.settings()
    if not cfg.daily_report:
        return False
    moment = datetime.fromtimestamp(time.time() if now is None else now)
    return moment.hour >= cfg.daily_report_hour and store.meta("daily_report_sent") != moment.strftime("%Y-%m-%d")


async def send(store, brain, outbox, health=None, now=None, scheduled=False):
    """Send the report to every enabled destination that is not scoped to one machine."""
    moment = time.time() if now is None else now
    text, _ = build(store, brain, health, moment)
    title, _, body = text.partition("\n")
    results = []
    for dest in store.objects("destination"):
        if not dest.get("enabled") or dest.get("machine_id") or dest.get("source_id"):
            continue
        id = uid()
        payload = dict(schema_version=1, delivery_id=id, event_type="report", severity="INFO", machine="LogSentinel", title=title, summary=body, problem_id="daily-report")
        status, error = "failed", None
        try:
            status = await outbox.send(dest, payload)
        except Exception as exc:
            error = type(exc).__name__ + ": verify credentials, connectivity and destination"
        with store.connect() as db:
            db.execute(
                "INSERT INTO deliveries VALUES(?,?,?,?,?,?,?,?,?,?)",
                (id, dest["id"], "report", dumps(payload), status, 1, moment, moment, moment, error),
            )
        results.append(dict(destination=dest["name"], status=status, error=error))
    if scheduled:
        # Marked even when nothing could be sent: a broken destination must not
        # turn into a message every fifteen seconds once it is repaired.
        store.set_meta("daily_report_sent", datetime.fromtimestamp(moment).strftime("%Y-%m-%d"))
    return results
