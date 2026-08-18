"""orchestrator/incident_log.py — durable record of every incident the
pipeline has processed, backed by SQLite (incidents.db, gitignored,
generated at runtime).

One row per thread_id, upserted: a ticket that pauses at the approval
gate gets an initial row with decision='pending_approval', which is
then updated in place once it's approved/rejected and resumed. This is
what the dashboard's "recent tickets" feed and "auto-remediated vs.
escalated" counts are read from — nothing here is inferred from the
other DBs (mcp_server/remediation_log.db, approvals.db) after the fact.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "incidents.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    thread_id  TEXT PRIMARY KEY,
    ticket_id  TEXT NOT NULL,
    title      TEXT,
    severity   TEXT,
    issue_type TEXT,
    route      TEXT,
    decision   TEXT NOT NULL,
    reason     TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the incidents table if it doesn't exist yet."""
    conn = _connect()
    try:
        conn.execute(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def record(
    thread_id: str,
    ticket_id: str,
    title: str | None,
    severity: str | None,
    issue_type: str | None,
    route: str | None,
    decision: str,
    reason: str | None,
) -> None:
    """Upsert this thread's current outcome. created_at is only set on
    first insert; updated_at always reflects the latest call (e.g. when
    a pending_approval row is later updated to auto_remediated)."""
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO incidents
                (thread_id, ticket_id, title, severity, issue_type, route, decision, reason, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                title=excluded.title, severity=excluded.severity,
                issue_type=excluded.issue_type, route=excluded.route,
                decision=excluded.decision, reason=excluded.reason,
                updated_at=excluded.updated_at
            """,
            (thread_id, ticket_id, title, severity, issue_type, route, decision, reason, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def list_recent(limit: int = 20) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM incidents ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def count_by_decision() -> dict[str, int]:
    """e.g. {'auto_remediated': 4, 'escalated': 2, 'pending_approval': 1}."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT decision, COUNT(*) AS n FROM incidents GROUP BY decision"
        ).fetchall()
    finally:
        conn.close()
    return {row["decision"]: row["n"] for row in rows}
