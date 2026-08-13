"""SQLite-backed ticket store for the Intake MCP server.

`tickets.db` is a generated artifact (gitignored, not committed). On first
use it's created and seeded from data/tickets_seed.json, a versioned fixture
of ~12 fake IT tickets across a handful of systems. Real code just queries
the SQLite table — the JSON file exists so the seed data itself is
diffable in git, not so it's read at request time.
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "tickets.db"
SEED_PATH = Path(__file__).resolve().parent / "data" / "tickets_seed.json"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id       TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    severity        TEXT NOT NULL,
    affected_system TEXT NOT NULL,
    status          TEXT NOT NULL
);
"""

# Fallback for any ticket ID not in the store, so the tool never "fails"
# outright while we're still stubbing things out.
_DEFAULT_TICKET = {
    "title": "Unspecified issue reported",
    "description": "No further detail was provided when the ticket was logged.",
    "severity": "medium",
    "affected_system": "unknown",
    "status": "open",
}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the tickets table and seed it if it's empty.

    Safe to call on every startup — seeding only happens when the table
    has zero rows, so it won't clobber data added since the seed ran.
    """
    conn = _connect()
    try:
        conn.execute(_SCHEMA)
        row_count = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
        if row_count == 0:
            tickets = json.loads(SEED_PATH.read_text(encoding="utf-8"))
            conn.executemany(
                """
                INSERT INTO tickets
                    (ticket_id, title, description, severity, affected_system, status)
                VALUES (:ticket_id, :title, :description, :severity, :affected_system, :status)
                """,
                tickets,
            )
            conn.commit()
    finally:
        conn.close()


def get_ticket(ticket_id: str) -> dict:
    """Look up a ticket by ID via a real SQL query.

    Returns the matching row as a dict, or a synthetic fallback record
    (tagged with the requested ticket_id) if no row matches.
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return {**_DEFAULT_TICKET, "ticket_id": ticket_id}
    return dict(row)
