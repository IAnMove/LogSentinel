"""The central's memory of each machine: inventories, their changes, and activity.

An inventory is kept whole only when it differs from the previous one; what
changed between two is written as rows (package added, port closed, user
gone), computed here and not by a model, so the history can be trusted and
searched. Activity is one row per command with its directory and project as
columns of their own: the question this exists for is "where did I work on
that", and it has to be answerable with an index, not by reading everything.

None of this is ever placed in the automatic review. Command lines and package
lists reach the model only when the operator asks a question about them.
"""

from __future__ import annotations

import gzip
import json
import time
from typing import Literal

from pydantic import Field

from .models import Model
from .store import dumps

CATEGORIES = ("system", "packages", "services", "ports", "users")
SNAPSHOTS_KEPT = 30
MAX_CHANGES_PER_INVENTORY = 5000


class BrainConfig(Model):
    enabled: bool = False
    mode: Literal["local", "remote"] = "remote"
    activity: bool = True
    inventory_interval_seconds: int = Field(default=86400, ge=300, le=7 * 86400)
    retention_days: int = Field(default=365, ge=1, le=3650)


class InventoryItem(Model):
    id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    kind: Literal["inventory"]
    observed: float = Field(ge=0, le=10**12)
    digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]+$")
    data: dict[str, dict[str, str]]
    errors: list[str] = Field(default_factory=list, max_length=20)


class CommandItem(Model):
    id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_.:-]+$")
    kind: Literal["command"]
    observed: float = Field(ge=0, le=10**12)
    user: str = Field(default="", max_length=64)
    cwd: str = Field(default="", max_length=500)
    project: str = Field(default="", max_length=120)
    command: str = Field(min_length=1, max_length=2000)


def like(text):
    """A LIKE pattern matching the text literally, wherever it appears."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%" + escaped + "%"


def differences(before, after):
    """Rows describing how one inventory differs from the previous one."""
    rows = []
    for category in CATEGORIES:
        # A category a reader could not produce is unknown, not empty: saying
        # "every package removed" because dpkg failed once would be a lie.
        if category not in before or category not in after:
            continue
        old, new = before[category], after[category]
        for item in sorted(set(old) | set(new)):
            if item not in old:
                rows.append((category, "added", item, "", new[item]))
            elif item not in new:
                rows.append((category, "removed", item, old[item], ""))
            elif old[item] != new[item]:
                rows.append((category, "changed", item, old[item], new[item]))
    return rows[:MAX_CHANGES_PER_INVENTORY]


class BrainStore:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS brain_snapshots(machine_id TEXT,id TEXT,observed REAL,received REAL,digest TEXT,data BLOB,PRIMARY KEY(machine_id,id));
                CREATE INDEX IF NOT EXISTS brain_snapshot_time ON brain_snapshots(machine_id,observed);
                CREATE TABLE IF NOT EXISTS brain_changes(id INTEGER PRIMARY KEY,machine_id TEXT,observed REAL,category TEXT,action TEXT,item TEXT,before TEXT,after TEXT);
                CREATE INDEX IF NOT EXISTS brain_change_time ON brain_changes(machine_id,observed);
                CREATE TABLE IF NOT EXISTS brain_commands(machine_id TEXT,id TEXT,observed REAL,user TEXT,cwd TEXT,project TEXT,command TEXT,PRIMARY KEY(machine_id,id));
                CREATE INDEX IF NOT EXISTS brain_command_time ON brain_commands(machine_id,observed);
                CREATE INDEX IF NOT EXISTS brain_command_project ON brain_commands(project,observed);
                CREATE INDEX IF NOT EXISTS brain_command_recent ON brain_commands(observed);
            """
            )

    def config(self, machine):
        data = self.store.get("brain_config", "brain:" + machine) or {}
        return BrainConfig.model_validate(
            {k: v for k, v in data.items() if k not in ("id", "machine_id")}
        )

    def configure(self, machine, config):
        self.store.put(
            "brain_config", dict(config.model_dump(), machine_id=machine), "brain:" + machine
        )
        self.store.audit("brain_config", machine)

    # --- writing -------------------------------------------------------------

    def latest(self, machine, db=None):
        def read(db):
            row = db.execute(
                "SELECT id,observed,received,digest,data FROM brain_snapshots WHERE machine_id=? ORDER BY observed DESC LIMIT 1",
                (machine,),
            ).fetchone()
            if not row:
                return None
            return dict(
                id=row["id"],
                observed=row["observed"],
                received=row["received"],
                digest=row["digest"],
                data=json.loads(gzip.decompress(row["data"])),
            )

        if db is not None:
            return read(db)
        with self.store.connect() as db:
            return read(db)

    def receive_inventory(self, machine, item):
        """Store an inventory and what changed since the last. True when new."""
        now = time.time()
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM brain_snapshots WHERE machine_id=? AND id=?", (machine, item.id)
            ).fetchone():
                return False
            previous = self.latest(machine, db)
            if previous and item.observed <= previous["observed"]:
                return False  # late or replayed; the newer picture already stands
            db.execute(
                "INSERT OR REPLACE INTO meta VALUES(?,?)",
                (
                    "brain_seen:" + machine,
                    dumps(dict(observed=item.observed, received=now, errors=item.errors)),
                ),
            )
            if previous and previous["digest"] == item.digest:
                return False  # nothing changed; only the time it was last seen
            if previous:
                db.executemany(
                    "INSERT INTO brain_changes(machine_id,observed,category,action,item,before,after) VALUES(?,?,?,?,?,?,?)",
                    [(machine, item.observed, *row) for row in differences(previous["data"], item.data)],
                )
            db.execute(
                "INSERT INTO brain_snapshots VALUES(?,?,?,?,?,?)",
                (machine, item.id, item.observed, now, item.digest, gzip.compress(dumps(item.data).encode())),
            )
            db.execute(
                "DELETE FROM brain_snapshots WHERE machine_id=? AND id NOT IN (SELECT id FROM brain_snapshots WHERE machine_id=? ORDER BY observed DESC LIMIT ?)",
                (machine, machine, SNAPSHOTS_KEPT),
            )
        return True

    def receive_commands(self, machine, items):
        with self.store.connect() as db:
            return db.executemany(
                "INSERT OR IGNORE INTO brain_commands VALUES(?,?,?,?,?,?,?)",
                [(machine, i.id, i.observed, i.user, i.cwd, i.project, i.command) for i in items],
            ).rowcount

    # --- reading -------------------------------------------------------------

    def status(self, machine):
        now = time.time()
        config = self.config(machine)
        try:
            seen = json.loads(self.store.meta("brain_seen:" + machine) or "{}")
        except ValueError:
            seen = {}
        with self.store.connect() as db:
            counts = db.execute(
                "SELECT count(*) total,sum(observed>=?) day,sum(observed>=?) week,max(observed) last FROM brain_commands WHERE machine_id=?",
                (now - 86400, now - 7 * 86400, machine),
            ).fetchone()
            changes = db.execute(
                "SELECT count(*) FROM brain_changes WHERE machine_id=? AND observed>=?",
                (machine, now - 7 * 86400),
            ).fetchone()[0]
        latest = self.latest(machine)
        return dict(
            machine_id=machine,
            config=config.model_dump(),
            token_configured=bool(self.store.meta("brain_token:" + machine)),
            inventory_observed=seen.get("observed"),
            inventory_errors=seen.get("errors", []),
            system=(latest or {}).get("data", {}).get("system", {}),
            counts={
                category: len((latest or {}).get("data", {}).get(category, {}))
                for category in CATEGORIES
                if category != "system"
            },
            changes_week=changes,
            commands_total=counts["total"] or 0,
            commands_day=counts["day"] or 0,
            commands_week=counts["week"] or 0,
            last_command=counts["last"],
            error=self.store.meta("brain_error:" + machine) or "",
        )

    def inventory(self, machine, category="", query="", limit=500):
        latest = self.latest(machine)
        if not latest:
            return dict(observed=None, items=[], total=0)
        needle = query.lower()
        items = [
            dict(category=name, item=item, value=value)
            for name in CATEGORIES
            if not category or name == category
            for item, value in sorted(latest["data"].get(name, {}).items())
            if not needle or needle in item.lower() or needle in value.lower()
        ]
        return dict(observed=latest["observed"], items=items[:limit], total=len(items))

    def changes(self, machine="", days=30, limit=500):
        since = time.time() - days * 86400
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT machine_id,observed,category,action,item,before,after FROM brain_changes WHERE observed>=? AND (?='' OR machine_id=?) ORDER BY observed DESC,id LIMIT ?",
                (since, machine, machine, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def activity(self, machine="", project="", query="", days=30, limit=200, before=None):
        since = time.time() - days * 86400
        where = ["observed>=?"]
        values: list = [since]
        if before is not None:
            where.append("observed<?")
            values.append(before)
        if machine:
            where.append("machine_id=?")
            values.append(machine)
        if project:
            where.append("(project=? OR (project='' AND cwd=?))")
            values += [project, project]
        if query:
            where.append("(command LIKE ? ESCAPE '\\' OR cwd LIKE ? ESCAPE '\\' OR project LIKE ? ESCAPE '\\')")
            values += [like(query)] * 3
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT machine_id,id,observed,user,cwd,project,command FROM brain_commands WHERE "
                + " AND ".join(where)
                + " ORDER BY observed DESC LIMIT ?",
                (*values, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def projects(self, days=30, machine="", limit=200):
        """Where each project was worked on: one row per project and machine.

        Outside a repository there is no project name, so the directory stands
        in for it; work in /etc/nginx is still findable as that."""
        since = time.time() - days * 86400
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT CASE WHEN project='' THEN cwd ELSE project END label,project!='' repository,machine_id,count(*) commands,min(observed) first,max(observed) last "
                "FROM brain_commands WHERE observed>=? AND (?='' OR machine_id=?) GROUP BY label,repository,machine_id ORDER BY last DESC LIMIT ?",
                (since, machine, machine, limit),
            ).fetchall()
        return [dict(row, repository=bool(row["repository"])) for row in rows]

    def days(self, days=14, machine=""):
        """What each machine was used for on each day (UTC), newest first."""
        since = time.time() - days * 86400
        with self.store.connect() as db:
            rows = db.execute(
                "SELECT date(observed,'unixepoch') day,machine_id,CASE WHEN project='' THEN cwd ELSE project END label,count(*) commands,min(observed) first,max(observed) last "
                "FROM brain_commands WHERE observed>=? AND (?='' OR machine_id=?) GROUP BY day,machine_id,label ORDER BY day DESC,machine_id,commands DESC",
                (since, machine, machine),
            ).fetchall()
        return [dict(row) for row in rows]

    # --- housekeeping --------------------------------------------------------

    def prune(self):
        removed = 0
        now = time.time()
        with self.store.connect() as db:
            for machine in self.store.objects("machine"):
                cutoff = now - self.config(machine["id"]).retention_days * 86400
                for table in ("brain_commands", "brain_changes"):
                    removed += db.execute(
                        f"DELETE FROM {table} WHERE machine_id=? AND observed<?",
                        (machine["id"], cutoff),
                    ).rowcount
        return removed
