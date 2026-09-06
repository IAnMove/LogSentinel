"""Persistent SQLite storage for adaptive memory, rules, and alert history."""

from __future__ import annotations
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any, Dict, List, Optional
from logsentinel.core.models import (
    Alert,
    AlertStatus,
    Category,
    Incident,
    LLMVerdict,
    MemoryRule,
    MemoryRuleType,
    Severity,
)


class MemoryStore:
    """SQLite-backed persistent store for memory rules and alerts."""

    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        """Create database tables if they do not exist."""
        with closing(self._get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rules (
                    id TEXT PRIMARY KEY,
                    rule_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    description TEXT,
                    created_at TEXT NOT NULL,
                    hit_count INTEGER DEFAULT 0,
                    last_matched TEXT,
                    is_active INTEGER DEFAULT 1,
                    metadata TEXT DEFAULT '{}'
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    category TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    service TEXT NOT NULL,
                    raw_incident TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    suppression_reason TEXT,
                    user_feedback TEXT,
                    channels_notified TEXT DEFAULT '[]'
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS feedback_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    alert_id TEXT,
                    user_instruction TEXT NOT NULL,
                    rule_created_id TEXT
                )
            """)
            conn.commit()

    # --- Memory Rules Operations ---

    def add_rule(self, rule: MemoryRule) -> MemoryRule:
        """Insert or update a memory rule."""
        with closing(self._get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO rules (
                    id, rule_type, content, description, created_at,
                    hit_count, last_matched, is_active, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                rule.id,
                rule.rule_type.value,
                rule.content,
                rule.description,
                rule.created_at.isoformat(),
                rule.hit_count,
                rule.last_matched.isoformat() if rule.last_matched else None,
                1 if rule.is_active else 0,
                json.dumps(rule.metadata),
            ))
            conn.commit()
        return rule

    def get_rule(self, rule_id: str) -> Optional[MemoryRule]:
        """Retrieve a rule by its ID."""
        with closing(self._get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM rules WHERE id = ?", (rule_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_rule(row)

    def list_rules(self, active_only: bool = True, rule_type: Optional[MemoryRuleType] = None) -> List[MemoryRule]:
        """List stored memory rules."""
        query = "SELECT * FROM rules WHERE 1=1"
        params: List[Any] = []
        if active_only:
            query += " AND is_active = 1"
        if rule_type:
            query += " AND rule_type = ?"
            params.append(rule_type.value)
        query += " ORDER BY created_at DESC"

        with closing(self._get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_rule(r) for r in rows]

    def record_rule_hit(self, rule_id: str) -> None:
        """Increment hit count and update last matched timestamp."""
        now_str = datetime.now(timezone.utc).isoformat()
        with closing(self._get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE rules
                SET hit_count = hit_count + 1, last_matched = ?
                WHERE id = ?
            """, (now_str, rule_id))
            conn.commit()

    def delete_rule(self, rule_id: str) -> bool:
        """Delete a rule by ID."""
        with closing(self._get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
            conn.commit()
            return cursor.rowcount > 0

    def set_rule_active(self, rule_id: str, is_active: bool) -> bool:
        """Enable or disable a rule."""
        with closing(self._get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE rules SET is_active = ? WHERE id = ?", (1 if is_active else 0, rule_id))
            conn.commit()
            return cursor.rowcount > 0

    def clear_all_rules(self) -> int:
        """Delete all rules."""
        with closing(self._get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM rules")
            conn.commit()
            return cursor.rowcount

    # --- Alerts History Operations ---

    def save_alert(self, alert: Alert) -> None:
        """Persist an alert record."""
        with closing(self._get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO alerts (
                    id, created_at, status, severity, category,
                    title, summary, service, raw_incident, verdict,
                    suppression_reason, user_feedback, channels_notified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                alert.id,
                alert.created_at.isoformat(),
                alert.status.value,
                alert.verdict.severity.value,
                alert.verdict.category.value,
                alert.verdict.title,
                alert.verdict.summary,
                alert.incident.service,
                json.dumps(alert.incident.model_dump(), default=str),
                json.dumps(alert.verdict.model_dump(), default=str),
                alert.suppression_reason,
                alert.user_feedback,
                json.dumps(alert.channels_notified),
            ))
            conn.commit()

    def get_alert(self, alert_id: str) -> Optional[Alert]:
        """Retrieve an alert by ID."""
        with closing(self._get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_alert(row)

    def list_alerts(self, limit: int = 50, status: Optional[AlertStatus] = None) -> List[Alert]:
        """List recorded alerts."""
        query = "SELECT * FROM alerts WHERE 1=1"
        params: List[Any] = []
        if status:
            query += " AND status = ?"
            params.append(status.value)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with closing(self._get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_alert(r) for r in rows]

    def update_alert_status(self, alert_id: str, status: AlertStatus, feedback: Optional[str] = None) -> bool:
        """Update an alert's status and feedback."""
        with closing(self._get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE alerts
                SET status = ?, user_feedback = COALESCE(?, user_feedback)
                WHERE id = ?
            """, (status.value, feedback, alert_id))
            conn.commit()
            return cursor.rowcount > 0

    def record_feedback(self, alert_id: Optional[str], instruction: str, rule_id: Optional[str]) -> None:
        """Record a feedback interaction."""
        now_str = datetime.now(timezone.utc).isoformat()
        with closing(self._get_connection()) as conn, conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO feedback_log (created_at, alert_id, user_instruction, rule_created_id)
                VALUES (?, ?, ?, ?)
            """, (now_str, alert_id, instruction, rule_id))
            conn.commit()

    # --- Helpers ---

    def _row_to_rule(self, row: sqlite3.Row) -> MemoryRule:
        return MemoryRule(
            id=row["id"],
            rule_type=MemoryRuleType(row["rule_type"]),
            content=row["content"],
            description=row["description"],
            created_at=datetime.fromisoformat(row["created_at"]),
            hit_count=row["hit_count"],
            last_matched=datetime.fromisoformat(row["last_matched"]) if row["last_matched"] else None,
            is_active=bool(row["is_active"]),
            metadata=json.loads(row["metadata"] or "{}"),
        )

    def _row_to_alert(self, row: sqlite3.Row) -> Alert:
        incident_data = json.loads(row["raw_incident"])
        verdict_data = json.loads(row["verdict"])
        return Alert(
            id=row["id"],
            created_at=datetime.fromisoformat(row["created_at"]),
            status=AlertStatus(row["status"]),
            incident=Incident.model_validate(incident_data),
            verdict=LLMVerdict.model_validate(verdict_data),
            suppression_reason=row["suppression_reason"],
            user_feedback=row["user_feedback"],
            channels_notified=json.loads(row["channels_notified"] or "[]"),
        )
