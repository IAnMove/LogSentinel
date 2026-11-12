"""Keeping the list of problems to what deserves a look.

Three things made the list grow without bound. The same fault reported with a
slightly different set of lines became a new problem each time; nothing ever
closed a problem that had stopped happening; and there was no way to say "I
know, it does not matter" that survived the next occurrence. This module holds
the three answers: findings join the open problem they overlap with, problems
quiet for long enough are resolved (and reopen by themselves if they return),
and an ignored problem stays ignored and silent however often it recurs.
"""

from __future__ import annotations

import hashlib
import time

from .store import dumps

CHECK_SECONDS = 3600
ACTIONS = ("resolve", "ignore", "reopen")
STATUS = {"resolve": "resolved", "ignore": "ignored", "reopen": "open"}
_last_check = {"at": 0.0}


def key_hashes(keys):
    return sorted({hashlib.sha256(dumps(key).encode()).hexdigest()[:32] for key in keys})


def matching_problem(db, machine, hashes):
    """The existing problem a finding with these line shapes belongs to, if any.

    At least half of the finding's shapes must already belong to one problem:
    one shared routine line is not the same fault, most of them is."""
    if not hashes:
        return None
    rows = db.execute(
        "SELECT k.problem_id,count(*) n FROM problem_keys k JOIN problems p ON p.id=k.problem_id "
        "WHERE k.machine_id=? AND k.key IN (%s) GROUP BY k.problem_id ORDER BY n DESC,max(p.last_seen) DESC LIMIT 1"
        % ",".join("?" * len(hashes)),
        (machine, *hashes),
    ).fetchone()
    if not rows or rows["n"] * 2 < len(hashes):
        return None
    return db.execute("SELECT * FROM problems WHERE id=?", (rows["problem_id"],)).fetchone()


def remember(db, machine, hashes, problem_id):
    db.executemany(
        "INSERT OR IGNORE INTO problem_keys VALUES(?,?,?)",
        [(machine, h, problem_id) for h in hashes],
    )


def set_status(store, ids, action):
    if action not in ACTIONS:
        raise ValueError("Unknown action")
    ids = [i for i in ids if isinstance(i, str)][:1000]
    if not ids:
        return 0
    with store.connect() as db:
        changed = db.execute(
            "UPDATE problems SET status=? WHERE id IN (%s) AND status!=?" % ",".join("?" * len(ids)),
            (STATUS[action], *ids, STATUS[action]),
        ).rowcount
    store.audit(action + "_by_user", ids[0] if len(ids) == 1 else "", dumps(dict(count=changed)))
    return changed


def auto_resolve(store, now=None):
    """Resolve open problems not seen for the configured number of days."""
    now = time.time() if now is None else now
    days = store.settings().auto_resolve_days
    if not days:
        return 0
    with store.connect() as db:
        changed = db.execute(
            "UPDATE problems SET status='resolved' WHERE status='open' AND last_seen<?",
            (now - days * 86400,),
        ).rowcount
    if changed:
        store.audit("auto_resolved", "", dumps(dict(count=changed, quiet_days=days)))
    return changed


def tick(store, now=None):
    now = time.time() if now is None else now
    if now - _last_check["at"] < CHECK_SECONDS:
        return 0
    _last_check["at"] = now
    return auto_resolve(store, now)


def counts(store, machine=""):
    with store.connect() as db:
        rows = db.execute(
            "SELECT status,count(*) n FROM problems WHERE ?='' OR machine_id=? GROUP BY status",
            (machine, machine),
        ).fetchall()
    found = {row["status"]: row["n"] for row in rows}
    return {status: found.get(status, 0) for status in ("open", "ignored", "resolved")}
