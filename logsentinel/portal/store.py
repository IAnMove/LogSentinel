"""Transactional event ledger with immutable compressed SQLite segments.

Segments and event cursors commit together in one FULL synchronous transaction.
Keeping blobs in SQLite makes backup and recovery atomic across their references.
"""

from __future__ import annotations
import gzip
import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from .models import Settings, destination_identity


def uid():
    return secrets.token_hex(12)


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class Store:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / "sentinel.db"
        with self.connect() as db:
            db.executescript(
                """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS objects(id TEXT PRIMARY KEY,kind TEXT NOT NULL,data TEXT NOT NULL,created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS objects_kind ON objects(kind);
            CREATE TABLE IF NOT EXISTS cursors(source_id TEXT,path TEXT,data TEXT,PRIMARY KEY(source_id,path));
            CREATE TABLE IF NOT EXISTS segments(id TEXT PRIMARY KEY,source_id TEXT,created REAL,raw_bytes INTEGER,data BLOB,sha TEXT);
            CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,source_id TEXT,machine_id TEXT,segment_id TEXT,ordinal INTEGER,received REAL,event_time TEXT,service TEXT,status TEXT,origin TEXT,UNIQUE(source_id,origin));
            CREATE INDEX IF NOT EXISTS events_status ON events(status,received);
            CREATE INDEX IF NOT EXISTS events_scope ON events(machine_id,source_id,received);
            CREATE INDEX IF NOT EXISTS events_time ON events(source_id,julianday(event_time));
            CREATE INDEX IF NOT EXISTS events_received ON events(source_id,received);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,machine_id TEXT,event_ids TEXT,status TEXT,created REAL,updated REAL,attempts INTEGER DEFAULT 0,config TEXT,error TEXT);
            CREATE TABLE IF NOT EXISTS problems(id TEXT PRIMARY KEY,machine_id TEXT,fingerprint TEXT,title TEXT,severity TEXT,status TEXT,first_seen REAL,last_seen REAL,count INTEGER,data TEXT,UNIQUE(machine_id,fingerprint));
            CREATE TABLE IF NOT EXISTS appearances(problem_id TEXT,event_id TEXT,PRIMARY KEY(problem_id,event_id));
            CREATE TABLE IF NOT EXISTS revisions(id TEXT PRIMARY KEY,problem_id TEXT,created REAL,data TEXT);
            CREATE TABLE IF NOT EXISTS usage(id TEXT PRIMARY KEY,job_id TEXT,machine_id TEXT,source_ids TEXT,kind TEXT,created REAL,input_tokens INTEGER,output_tokens INTEGER,duration REAL,status TEXT,detail TEXT);
            CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY,destination_id TEXT,problem_id TEXT,payload TEXT,status TEXT,attempts INTEGER,created REAL,updated REAL,next_try REAL,error TEXT);
            CREATE INDEX IF NOT EXISTS deliveries_due ON deliveries(status,next_try);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,created REAL,action TEXT,object_id TEXT,detail TEXT);
            CREATE TABLE IF NOT EXISTS metrics(source_id TEXT,key TEXT,value INTEGER,PRIMARY KEY(source_id,key));
            """
            )
            version = db.execute(
                "SELECT value FROM meta WHERE key='schema_version'"
            ).fetchone()
            if version and version[0] != "1":
                raise RuntimeError(
                    "Unsupported schema version; restore with a compatible version"
                )
            db.execute("INSERT OR IGNORE INTO meta VALUES('schema_version','1')")
            db.execute(
                "INSERT OR IGNORE INTO meta VALUES('settings',?)",
                (dumps(Settings().model_dump()),),
            )
            db.execute(
                "INSERT OR IGNORE INTO meta VALUES('admin_token',?)",
                (secrets.token_urlsafe(32),),
            )
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def meta(self, key):
        with self.connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
            return row[0] if row else None

    def set_meta(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES(?,?)", (key, value))

    def settings(self):
        return Settings.model_validate_json(self.meta("settings"))

    def monitoring_active(self, machine_id):
        machine = self.get("machine", machine_id)
        return bool(
            machine
            and not machine.get("monitoring_paused")
            and not machine.get("deletion_pending")
        )

    def audit(self, action, object_id="", detail=""):
        with self.connect() as db:
            db.execute(
                "INSERT INTO audit(created,action,object_id,detail) VALUES(?,?,?,?)",
                (time.time(), action, object_id, detail[:1000]),
            )

    def objects(self, kind):
        with self.connect() as db:
            return [
                dict(json.loads(r["data"]), id=r["id"])
                for r in db.execute(
                    "SELECT * FROM objects WHERE kind=? ORDER BY created", (kind,)
                )
            ]

    def get(self, kind, id):
        with self.connect() as db:
            r = db.execute(
                "SELECT data FROM objects WHERE id=? AND kind=?", (id, kind)
            ).fetchone()
            return dict(json.loads(r[0]), id=id) if r else None

    def put(self, kind, data, id=None):
        id = id or uid()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if (
                kind != "machine_deletion"
                and data.get("machine_id")
                and db.execute(
                    "SELECT 1 FROM meta WHERE key=?",
                    ("deleted_machine:" + data["machine_id"],),
                ).fetchone()
            ):
                raise ValueError("Machine has been deleted")
            changed_destination = False
            if kind == "destination":
                previous = db.execute(
                    "SELECT data FROM objects WHERE id=? AND kind=?", (id, kind)
                ).fetchone()
                changed_destination = bool(
                    previous
                    and destination_identity(json.loads(previous[0]))
                    != destination_identity(data)
                )
            db.execute(
                "INSERT INTO objects VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (id, kind, dumps(data), time.time()),
            )
            if kind == "destination" and (
                not data.get("enabled") or changed_destination
            ):
                db.execute(
                    "UPDATE deliveries SET status='cancelled' WHERE destination_id=? AND status IN ('pending','retry')",
                    (id,),
                )
        self.audit("save:" + kind, id)
        return id

    def delete(self, kind, id):
        with self.connect() as db:
            db.execute("DELETE FROM objects WHERE kind=? AND id=?", (kind, id))
            if kind == "destination":
                db.execute(
                    "UPDATE deliveries SET status='cancelled' WHERE destination_id=? AND status IN ('pending','retry')",
                    (id,),
                )
        self.audit("delete:" + kind, id)

    def cursor(self, source_id, path):
        with self.connect() as db:
            row = db.execute(
                "SELECT data FROM cursors WHERE source_id=? AND path=?",
                (source_id, path),
            ).fetchone()
            return json.loads(row[0]) if row else None

    def metric(self, source_id, key, value):
        with self.connect() as db:
            self._metric(db, source_id, key, value)

    @staticmethod
    def _metric(db, source, key, value):
        db.execute(
            "INSERT INTO metrics VALUES(?,?,?) ON CONFLICT(source_id,key) DO UPDATE SET value=value+excluded.value",
            (source, key, value),
        )

    def size(self):
        return sum(
            p.stat().st_size for p in self.directory.glob("sentinel.db*") if p.is_file()
        )

    def ingest(self, source, entries, cursor_path=None, cursor=None):
        """Origin IDs are stable source positions or sender event IDs, never message hashes."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            machine = db.execute(
                "SELECT data FROM objects WHERE kind='machine' AND id=?",
                (source["machine_id"],),
            ).fetchone()
            if (
                machine
                and any(
                    json.loads(machine[0]).get(k)
                    for k in ("monitoring_paused", "deletion_pending")
                )
            ) or db.execute(
                "SELECT 1 FROM meta WHERE key=?",
                ("deleted_machine:" + source["machine_id"],),
            ).fetchone():
                raise ValueError(
                    "Machine monitoring is paused or deleted; retain and retry these events"
                )
            unique = []
            seen = set()
            for item in entries:
                origin = item["origin"]
                if (
                    origin in seen
                    or db.execute(
                        "SELECT 1 FROM events WHERE source_id=? AND origin=?",
                        (source["id"], origin),
                    ).fetchone()
                ):
                    continue
                seen.add(origin)
                unique.append(dict(item, id=uid()))
            if unique:
                raw = dumps(unique).encode()
                if (
                    self.size() + len(raw) * 2
                    > self.settings().disk_limit_mb * 1024 * 1024
                ):
                    raise OSError(
                        "Storage quota reached; incoming data was not acknowledged"
                    )
                sid = uid()
                now = time.time()
                db.execute(
                    "INSERT INTO segments VALUES(?,?,?,?,?,?)",
                    (
                        sid,
                        source["id"],
                        now,
                        len(raw),
                        gzip.compress(raw, mtime=0),
                        hashlib.sha256(raw).hexdigest(),
                    ),
                )
                for i, item in enumerate(unique):
                    db.execute(
                        "INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (
                            item["id"],
                            source["id"],
                            source["machine_id"],
                            sid,
                            i,
                            now,
                            item.get("timestamp", ""),
                            item.get("service", "unknown"),
                            "pending",
                            item["origin"],
                        ),
                    )
                self._metric(db, source["id"], "events_ingested", len(unique))
                self._metric(
                    db,
                    source["id"],
                    "logical_bytes",
                    sum(
                        len(e.get("raw", e.get("message", "")).encode()) for e in unique
                    ),
                )
            if cursor_path is not None:
                db.execute(
                    "INSERT OR REPLACE INTO cursors VALUES(?,?,?)",
                    (source["id"], cursor_path, dumps(cursor)),
                )
        return len(unique)

    def events(
        self,
        machine_id="",
        source_id="",
        status="",
        limit=100,
        offset=0,
        ids=None,
        newest=False,
    ):
        query = "SELECT * FROM events WHERE 1=1"
        params = []
        for key, value in [
            ("machine_id", machine_id),
            ("source_id", source_id),
            ("status", status),
        ]:
            if value:
                query += " AND " + key + "=?"
                params.append(value)
        if ids is not None:
            if not ids:
                return []
            query += " AND id IN (" + ",".join("?" for _ in ids) + ")"
            params.extend(ids)
        query += (
            " ORDER BY received DESC,rowid DESC LIMIT ? OFFSET ?"
            if newest
            else " ORDER BY received,rowid LIMIT ? OFFSET ?"
        )
        params.extend([min(limit, 5000), offset])
        with self.connect() as db:
            rows = db.execute(query, params).fetchall()
            cache = {}
            out = []
            for row in rows:
                sid = row["segment_id"]
                if sid not in cache:
                    segment = db.execute(
                        "SELECT data,sha FROM segments WHERE id=?", (sid,)
                    ).fetchone()
                    if segment is None:
                        continue
                    raw = gzip.decompress(segment["data"])
                    if hashlib.sha256(raw).hexdigest() != segment["sha"]:
                        raise ValueError("Segment checksum mismatch")
                    cache[sid] = json.loads(raw)
                out.append(dict(cache[sid][row["ordinal"]], **dict(row)))
            return out

    def neighbors(self, ids, radius=2):
        neighbors = []
        with self.connect() as db:
            for id in ids[:30]:
                row = db.execute(
                    "SELECT rowid,source_id FROM events WHERE id=?", (id,)
                ).fetchone()
                if not row:
                    continue
                for op, order in (("<", "DESC"), (">", "ASC")):
                    neighbors.extend(
                        r[0]
                        for r in db.execute(
                            f"SELECT id FROM events WHERE source_id=? AND rowid{op}? ORDER BY rowid {order} LIMIT ?",
                            (row["source_id"], row["rowid"], radius),
                        )
                    )
        return self.events(ids=list(dict.fromkeys(neighbors)), limit=150)

    def context(self, ids, seconds=300, limit=5000):
        """Look up nearby retained context by index, including recent history.

        Undated triggers use receipt time. They must never match the entire
        source. Triggers are retained first; context is a bounded sample of
        already captured events, not a promise about future arrivals.
        """
        limit = min(max(limit, 1), 5000)
        selected = dict.fromkeys(ids[:limit])
        with self.connect() as db:
            for id in ids[:100]:
                row = db.execute(
                    "SELECT source_id,julianday(event_time) moment,received FROM events WHERE id=?",
                    (id,),
                ).fetchone()
                if not row or seconds <= 0:
                    continue
                column = (
                    "julianday(event_time)" if row["moment"] is not None else "received"
                )
                moment = row["moment"] if row["moment"] is not None else row["received"]
                delta = seconds / 86400 if row["moment"] is not None else seconds
                # Both sides get a share; oldest events cannot crowd out the
                # closest context. Bound decompression to the final selection.
                for op, order, bound in (
                    ("<=", "DESC", moment - delta),
                    (">", "ASC", moment + delta),
                ):
                    candidates = db.execute(
                        f"SELECT id FROM events WHERE source_id=? AND {column} BETWEEN ? AND ? AND {column}{op}? ORDER BY {column} {order} LIMIT ?",
                        (
                            row["source_id"],
                            min(moment, bound),
                            max(moment, bound),
                            moment,
                            min(100, limit),
                        ),
                    )
                    for candidate in candidates:
                        if len(selected) < limit:
                            selected[candidate[0]] = None
        rows = {e["id"]: e for e in self.events(ids=list(selected), limit=limit)}
        return [rows[id] for id in selected if id in rows]

    def mark(self, ids, status):
        if not ids:
            return
        with self.connect() as db:
            db.executemany(
                "UPDATE events SET status=? WHERE id=?", [(status, i) for i in ids]
            )

    def rows(self, table, limit=100):
        if table not in (
            "jobs",
            "problems",
            "usage",
            "deliveries",
            "audit",
            "revisions",
        ):
            raise ValueError("Unknown table")
        with self.connect() as db:
            return [
                dict(r)
                for r in db.execute(
                    f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT ?",
                    (min(limit, 1000),),
                )
            ]

    def problem(self, id):
        with self.connect() as db:
            row = db.execute("SELECT * FROM problems WHERE id=?", (id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            result["data"] = json.loads(result["data"])
            counts = db.execute(
                "SELECT count(*) total,count(events.id) retained FROM appearances LEFT JOIN events ON events.id=appearances.event_id WHERE problem_id=?",
                (id,),
            ).fetchone()
            result["retained_evidence"] = counts["retained"]
            result["expired_evidence"] = counts["total"] - counts["retained"]
            refs = list(
                dict.fromkeys(
                    result["data"].get("evidence_ids", [])
                    + [
                        r[0]
                        for r in db.execute(
                            "SELECT event_id FROM appearances WHERE problem_id=? ORDER BY rowid DESC LIMIT 100",
                            (id,),
                        )
                    ]
                )
            )[:100]
            events = {e["id"]: e for e in self.events(ids=refs)}
            result["evidence"] = [events[ref] for ref in refs if ref in events]
            result["revisions"] = [
                dict(r)
                for r in db.execute(
                    "SELECT id,created,data FROM revisions WHERE problem_id=? ORDER BY created DESC LIMIT 20",
                    (id,),
                )
            ]
            return result

    def record_usage(
        self,
        job,
        machine,
        sources,
        kind,
        start,
        input_tokens,
        output_tokens,
        status,
        detail,
    ):
        with self.connect() as db:
            db.execute(
                "INSERT INTO usage VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    uid(),
                    job,
                    machine,
                    dumps(sources),
                    kind,
                    time.time(),
                    input_tokens,
                    output_tokens,
                    time.monotonic() - start,
                    status,
                    dumps(detail),
                ),
            )

    def stats(self, machine_id=""):
        with self.connect() as db:
            scope = " WHERE machine_id=?" if machine_id else ""
            args = (machine_id,) if machine_id else ()
            coverage = {
                r[0]: r[1]
                for r in db.execute(
                    "SELECT status,count(*) FROM events" + scope + " GROUP BY status",
                    args,
                )
            }
            metrics = [dict(r) for r in db.execute("SELECT * FROM metrics")]
            if machine_id:
                sources = {
                    o["id"]
                    for o in self.objects("source")
                    if o["machine_id"] == machine_id
                }
                metrics = [r for r in metrics if r["source_id"] in sources]
            usage = dict(
                db.execute(
                    "SELECT count(*) calls,sum(input_tokens) input_tokens,sum(output_tokens) output_tokens,sum(duration) seconds,sum(CASE WHEN input_tokens IS NULL OR output_tokens IS NULL THEN 1 ELSE 0 END) unknown_calls FROM usage"
                    + scope,
                    args,
                ).fetchone()
            )
            if machine_id:
                segments = dict(
                    db.execute(
                        "SELECT coalesce(sum(raw_bytes),0) original,coalesce(sum(length(data)),0) compressed FROM segments WHERE source_id IN (SELECT id FROM objects WHERE kind='source' AND json_extract(data,'$.machine_id')=?)",
                        (machine_id,),
                    ).fetchone()
                )
            else:
                segments = dict(
                    db.execute(
                        "SELECT coalesce(sum(raw_bytes),0) original,coalesce(sum(length(data)),0) compressed FROM segments"
                    ).fetchone()
                )
            per_source = {
                o["id"]: {
                    "source_id": o["id"],
                    "name": o["name"],
                    "logical_bytes": 0,
                    "events_ingested": 0,
                    "allocated_tokens": 0,
                    "unknown_calls": 0,
                }
                for o in self.objects("source")
                if not machine_id or o["machine_id"] == machine_id
            }
            for row in metrics:
                if row["source_id"] in per_source and row["key"] in (
                    "logical_bytes",
                    "events_ingested",
                ):
                    per_source[row["source_id"]][row["key"]] = row["value"]
            for row in db.execute(
                "SELECT source_ids,input_tokens,output_tokens,detail FROM usage"
                + scope,
                args,
            ):
                sources = json.loads(row["source_ids"])
                weights = json.loads(row["detail"]).get("source_bytes", {})
                total = sum(weights.values())
                for sid in sources:
                    if sid not in per_source:
                        continue
                    if row["input_tokens"] is None or row["output_tokens"] is None:
                        per_source[sid]["unknown_calls"] += 1
                    share = (
                        weights.get(sid, 0) / total
                        if total
                        else 1 / max(1, len(sources))
                    )
                    per_source[sid]["allocated_tokens"] += (
                        (row["input_tokens"] or 0) + (row["output_tokens"] or 0)
                    ) * share
            open_problems = db.execute(
                "SELECT count(*) FROM problems WHERE status='open'"
                + (" AND machine_id=?" if machine_id else ""),
                args,
            ).fetchone()[0]
            return {
                "open_problems": open_problems,
                "sources": list(per_source.values()),
                "coverage": coverage,
                "usage": usage,
                "metrics": metrics,
                "segments": segments,
                "disk_bytes": self.size(),
            }

    def recover(self):
        with self.connect() as db:
            db.execute(
                "UPDATE jobs SET status='retry',attempts=max(0,attempts-1),error='Interrupted during analysis',updated=? WHERE status='running'",
                (time.time(),),
            )
            # Older versions could strand an interrupted third attempt in a
            # retry state that the scheduler would never select.
            db.execute(
                "UPDATE jobs SET attempts=2 WHERE status='retry' AND attempts>=3 AND error IN ('Interrupted','Interrupted during analysis')"
            )
            db.execute(
                "UPDATE deliveries SET status='unknown',error='Interrupted during delivery' WHERE status='sending'"
            )

    def prune(self):
        cutoff = time.time() - self.settings().retention_days * 86400
        with self.connect() as db:
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM segments WHERE created<?", (cutoff,)
                )
            ]
            for sid in ids:
                db.execute("DELETE FROM events WHERE segment_id=?", (sid,))
                db.execute("DELETE FROM segments WHERE id=?", (sid,))
            if ids:
                self._metric(db, "", "segments_expired", len(ids))
            db.execute("PRAGMA wal_checkpoint(PASSIVE)") if not ids else None
        if ids:
            with self.connect() as db:
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                db.execute("VACUUM")
        return len(ids)

    def discard_sent(self):
        """Reclaim fully acknowledged sender segments without touching file cursors."""
        with self.connect() as db:
            ids = [
                r[0]
                for r in db.execute(
                    "SELECT id FROM segments WHERE NOT EXISTS (SELECT 1 FROM events WHERE segment_id=segments.id AND status!='sent')"
                )
            ]
            for sid in ids:
                db.execute("DELETE FROM events WHERE segment_id=?", (sid,))
                db.execute("DELETE FROM segments WHERE id=?", (sid,))
        if ids:
            with self.connect() as db:
                db.execute("VACUUM")
        return len(ids)

    def backup(self, target):
        target = Path(target)
        if target.exists():
            raise ValueError("Backup target already exists")
        with self.connect() as db, sqlite3.connect(target) as dest:
            db.backup(dest)
        os.chmod(target, 0o600)
        return target
