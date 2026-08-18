"""orchestrator/approvals.py — persistent queue of incidents paused at
the hard approval gate, backed by SQLite (approvals.db, gitignored,
generated at runtime).

Paired with the LangGraph checkpointer (see graph.py): a row here
records *that* a thread is paused waiting for a human decision; the
checkpointer separately holds the actual paused execution state.
Approving a row means resuming the matching thread_id via
graph.resume_incident(tools, thread_id, approved=True) — this module
itself never touches the graph, it's just the queue the dashboard reads
and writes.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "approvals.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS approvals (
    thread_id  TEXT PRIMARY KEY,
    ticket_id  TEXT NOT NULL,
    severity   TEXT,
    issue_type TEXT,
    action     TEXT NOT NULL,
    target     TEXT NOT NULL,
    reason     TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    decided_at TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the approvals table if it doesn't exist yet."""
    conn = _connect()
    try:
        conn.execute(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def create_pending(
    thread_id: str,
    ticket_id: str,
    severity: str | None,
    issue_type: str | None,
    action: str,
    target: str,
    reason: str,
) -> None:
    """Record a new pending approval. Safe to call again for the same
    thread_id (e.g. a retried run) -- resets it back to 'pending'."""
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO approvals
                (thread_id, ticket_id, severity, issue_type, action, target, reason, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                ticket_id=excluded.ticket_id, severity=excluded.severity,
                issue_type=excluded.issue_type, action=excluded.action,
                target=excluded.target, reason=excluded.reason,
                status='pending', created_at=excluded.created_at, decided_at=NULL
            """,
            (
                thread_id, ticket_id, severity, issue_type, action, target, reason,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_pending() -> list[dict]:
    """Oldest first, so the dashboard's queue reads top-to-bottom."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at ASC"
        ).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def mark_decided(thread_id: str, status: str) -> None:
    """status: 'approved' or 'rejected'."""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE approvals SET status = ?, decided_at = ? WHERE thread_id = ?",
            (status, datetime.now(timezone.utc).isoformat(), thread_id),
        )
        conn.commit()
    finally:
        conn.close()
