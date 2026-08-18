"""Unit tests for approvals.py — the pending-approval queue."""

import approvals


def _use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(approvals, "DB_PATH", tmp_path / "test_approvals.db")
    approvals.init_db()


def test_create_pending_appears_in_list_pending(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    approvals.create_pending(
        thread_id="t1", ticket_id="INC0012354", severity="medium",
        issue_type="network_latency", action="scale_out",
        target="vpn-auth-service", reason="needs approval",
    )

    pending = approvals.list_pending()
    assert len(pending) == 1
    assert pending[0]["thread_id"] == "t1"
    assert pending[0]["status"] == "pending"
    assert pending[0]["action"] == "scale_out"


def test_mark_decided_removes_from_pending_list(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    approvals.create_pending(
        thread_id="t1", ticket_id="INC0012354", severity="medium",
        issue_type="network_latency", action="scale_out",
        target="vpn-auth-service", reason="needs approval",
    )
    approvals.mark_decided("t1", "approved")

    assert approvals.list_pending() == []


def test_list_pending_only_returns_pending_status(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    approvals.create_pending(
        thread_id="t1", ticket_id="INC0012354", severity="medium",
        issue_type="network_latency", action="scale_out",
        target="vpn-auth-service", reason="r1",
    )
    approvals.create_pending(
        thread_id="t2", ticket_id="INC0012355", severity="medium",
        issue_type="high_cpu", action="restart_service",
        target="web-prod-cluster-03", reason="r2",
    )
    approvals.mark_decided("t1", "approved")

    pending = approvals.list_pending()
    assert [row["thread_id"] for row in pending] == ["t2"]


def test_create_pending_is_idempotent_for_same_thread_id(tmp_path, monkeypatch):
    """A retried run for the same thread_id should update, not duplicate."""
    _use_temp_db(tmp_path, monkeypatch)

    approvals.create_pending(
        thread_id="t1", ticket_id="INC0012354", severity="medium",
        issue_type="network_latency", action="scale_out",
        target="vpn-auth-service", reason="first reason",
    )
    approvals.create_pending(
        thread_id="t1", ticket_id="INC0012354", severity="medium",
        issue_type="network_latency", action="scale_out",
        target="vpn-auth-service", reason="updated reason",
    )

    pending = approvals.list_pending()
    assert len(pending) == 1
    assert pending[0]["reason"] == "updated reason"
