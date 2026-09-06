"""Observed SSH schedules: bounded event history, not an identity or trust oracle."""
from __future__ import annotations

from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sqlite3
from zoneinfo import ZoneInfo

from logsentinel.config import BehaviorConfig
from logsentinel.core.models import LogEntry


class BehaviorProfiler:
    """Score against strictly earlier history, then learn only non-anomalous events.

    Cold-start activity is unverified, not trusted. Coverage is observed access days,
    NOT proof that collection ran continuously. Unusual entries remain in alerts
    but are quarantined from this baseline to limit immediate self-poisoning.
    """

    def __init__(self, db_path: Path, config: BehaviorConfig):
        self.db_path = db_path
        self.config = config
        self.zone = ZoneInfo(config.timezone)
        with closing(sqlite3.connect(db_path)) as conn, conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS behavior_events (
                fingerprint TEXT PRIMARY KEY, entity TEXT NOT NULL,
                timestamp REAL NOT NULL, event_id TEXT NOT NULL)""")
            conn.execute("CREATE INDEX IF NOT EXISTS behavior_entity_time ON behavior_events(entity, timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS behavior_time ON behavior_events(timestamp)")

    def observe(self, entry: LogEntry) -> dict | None:
        if not self.config.enabled or 'timestamp' not in entry.model_fields_set or entry.metadata.get('timestamp_inferred'):
            return None
        if entry.timestamp.timestamp() > datetime.now(timezone.utc).timestamp() + 300:
            return None
        if entry.service.removesuffix('.service') not in {'sshd', 'ssh', 'sshd-session'}:
            return None
        match = re.match(r'^Accepted (?:publickey|password|keyboard-interactive(?:/pam)?) for (\S+) from (\S+) port \d+\b', entry.message)
        if not match:
            return None
        try:
            ip = str(ipaddress.ip_address(match[2]))
        except ValueError:
            return None
        at = entry.timestamp.astimezone(timezone.utc)
        local = at.astimezone(self.zone)
        entity = json.dumps([entry.hostname or entry.source_name, 'ssh', match[1], ip])
        # Same event via file/journald with identical time/message has one vote.
        fingerprint = hashlib.sha256(json.dumps([entity, at.isoformat(), entry.message]).encode()).hexdigest()
        timestamp = at.timestamp()
        day_type = 'weekend' if local.weekday() >= 5 else 'weekday'
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            rows = conn.execute(
                'SELECT timestamp, event_id FROM behavior_events WHERE entity=? AND timestamp>=? AND timestamp<? ORDER BY timestamp',
                (entity, timestamp - self.config.retention_days * 86400, timestamp),
            ).fetchall()
            prior = [datetime.fromtimestamp(row[0], self.zone) for row in rows]
            dates = {t.date() for t in prior}
            span = (prior[-1].date() - prior[0].date()).days if prior else 0
            counts = Counter('weekend' if t.weekday() >= 5 else 'weekday' for t in prior)
            hours = sorted({t.hour for t in prior if ('weekend' if t.weekday() >= 5 else 'weekday') == day_type})
            comparison_hours = hours or sorted({t.hour for t in prior})
            sufficient = len(prior) >= self.config.min_events and len(dates) >= self.config.min_days and span >= self.config.min_span_days
            anomalies = []
            if sufficient:
                if counts[day_type] == 0:
                    anomalies.append('unseen_day_type')
                if all(min(abs(local.hour - h), 24 - abs(local.hour - h)) > self.config.hour_tolerance for h in comparison_hours):
                    anomalies.append('unusual_hour')
            duplicate = conn.execute('SELECT 1 FROM behavior_events WHERE fingerprint=?', (fingerprint,)).fetchone() is not None
            newer = conn.execute('SELECT 1 FROM behavior_events WHERE entity=? AND timestamp>? LIMIT 1', (entity, timestamp)).fetchone()
            # Tolerance permits observation, not expansion of the learned hours.
            learned = not anomalies and not duplicate and not newer and (not sufficient or local.hour in comparison_hours)
            if learned:
                conn.execute('INSERT INTO behavior_events VALUES (?, ?, ?, ?)', (fingerprint, entity, timestamp, entry.id))
            # Watermark based retention: replaying old files cannot evict newer history.
            newest = conn.execute('SELECT MAX(timestamp) FROM behavior_events').fetchone()[0]
            if newest is not None:
                conn.execute('DELETE FROM behavior_events WHERE timestamp < ?', (newest - self.config.retention_days * 86400,))
            conn.execute('DELETE FROM behavior_events WHERE fingerprint IN (SELECT fingerprint FROM behavior_events ORDER BY timestamp DESC LIMIT -1 OFFSET ?)', (self.config.max_events,))
        return {
            'kind': 'ssh_success_schedule', 'entity': {'host': entry.hostname or entry.source_name, 'service': 'ssh', 'user': match[1], 'ip': ip},
            'event_id': entry.id, 'event_time': at.isoformat(), 'timezone': self.config.timezone,
            'local_hour': local.hour, 'local_day_type': day_type,
            'status': 'unusual' if anomalies else ('observed_schedule' if sufficient else 'insufficient_history'),
            'anomalies': anomalies, 'prior_events': len(prior), 'observed_days': len(dates), 'span_days': span,
            'prior_day_type_counts': {'weekday': counts['weekday'], 'weekend': counts['weekend']},
            'prior_hours': comparison_hours, 'prior_event_ids_sample': [row[1] for row in rows[-5:]],
            'history_start': prior[0].isoformat() if prior else None,
            'history_end': prior[-1].isoformat() if prior else None,
            'learned': learned, 'duplicate': duplicate,
            'limitations': 'Observed logins only; collection continuity is unknown. Cold-start baseline is unverified. IP is not identity. Unusual does not mean malicious.',
        }
