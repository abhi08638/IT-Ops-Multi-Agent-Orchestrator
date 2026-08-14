"""Mock remediation executor + audit log for the run_remediation MCP tool.

run_remediation() never touches a real system — it only builds a
human-readable description of the action it "would" take and records it
in remediation_log.db. This keeps a persistent, queryable audit trail
(consistent with the project's "every decision gets logged" design
intent) without ever running a real command. There is deliberately no
subprocess/os.system/eval/exec anywhere in this module — action and
target are only ever used to build a string and as parameterized SQL
values, never interpreted or executed.
"""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "remediation_log.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS remediation_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    action     TEXT NOT NULL,
    target     TEXT NOT NULL,
    message    TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the remediation_log table if it doesn't exist yet."""
    conn = _connect()
    try:
        conn.execute(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def run_remediation(action: str, target: str) -> dict:
    """Simulate running a remediation action against a target, and log it.

    This is a mock executor: it never runs a real command against
    `target`, regardless of what `action` contains. It only formats a
    description of what it "would" do and appends it to the audit log.
    The returned dict includes an explicit status/note so a caller can't
    mistake this for a real execution.
    """
    message = f"Would run action '{action}' against target '{target}'."
    created_at = datetime.now(timezone.utc).isoformat()

    conn = _connect()
    try:
        cursor = conn.execute(
            "INSERT INTO remediation_log (action, target, message, created_at) "
            "VALUES (?, ?, ?, ?)",
            (action, target, message, created_at),
        )
        conn.commit()
        log_id = cursor.lastrowid
    finally:
        conn.close()

    return {
        "id": log_id,
        "status": "simulated",
        "action": action,
        "target": target,
        "message": message,
        "created_at": created_at,
        "note": "Mock executor — no real command was run.",
    }
