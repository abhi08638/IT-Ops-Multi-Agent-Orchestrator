"""Unit tests for db.py — the SQLite-backed ticket store.

Each test points db.DB_PATH at a fresh temp file so tests never touch (or
depend on) the real tickets.db, and can run in any order.
"""

import json

import db


def _use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_tickets.db")
    db.init_db()


def test_init_db_seeds_from_fixture(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    seeded = json.loads(db.SEED_PATH.read_text(encoding="utf-8"))

    conn = db._connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    finally:
        conn.close()

    assert count == len(seeded)
    assert len(seeded) >= 10  # sanity check on the fixture itself


def test_get_ticket_returns_known_ticket(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    ticket = db.get_ticket("INC0012345")
    assert ticket["title"] == "Production web server unresponsive"
    assert ticket["severity"] == "critical"
    assert ticket["affected_system"] == "web-prod-cluster-03"


def test_get_ticket_unknown_id_falls_back_to_default(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    ticket = db.get_ticket("INC9999999")
    assert ticket["ticket_id"] == "INC9999999"
    assert ticket["status"] == db._DEFAULT_TICKET["status"]
    assert ticket["severity"] == db._DEFAULT_TICKET["severity"]


def test_get_ticket_does_not_mutate_default_template(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    db.get_ticket("INC0000001")
    db.get_ticket("INC0000002")
    assert "ticket_id" not in db._DEFAULT_TICKET


def test_init_db_is_idempotent(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    db.init_db()  # calling again shouldn't duplicate rows

    conn = db._connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0]
    finally:
        conn.close()

    seeded = json.loads(db.SEED_PATH.read_text(encoding="utf-8"))
    assert count == len(seeded)
