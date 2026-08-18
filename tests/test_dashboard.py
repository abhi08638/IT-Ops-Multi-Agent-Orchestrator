"""Smoke test for dashboard/app.py using Streamlit's AppTest harness.

Confirms the dashboard loads without exceptions and renders the
expected stats/queue given seeded data. The interactive "Approve"
button's full resume flow (spawning a real MCP subprocess) was
verified manually against the live running app in a real browser —
clicking Approve moved a ticket from Pending Approval to
Auto-remediated and updated both metrics and the queue in place. That
flow spawns a real subprocess and isn't a good fit for a fast
automated test, so it's not repeated here.
"""

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))

import approvals
import incident_log

DASHBOARD_PATH = str(Path(__file__).resolve().parent.parent / "dashboard" / "app.py")


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(approvals, "DB_PATH", tmp_path / "test_approvals.db")
    monkeypatch.setattr(incident_log, "DB_PATH", tmp_path / "test_incidents.db")
    approvals.init_db()
    incident_log.init_db()

    incident_log.record(
        thread_id="t1", ticket_id="INC0012346", title="VPN password reset",
        severity="low", issue_type="service_down", route="remediate",
        decision="auto_remediated", reason=None,
    )
    incident_log.record(
        thread_id="t2", ticket_id="INC0012345", title="Web server unresponsive",
        severity="critical", issue_type="service_down", route="escalate",
        decision="escalated", reason="too risky",
    )
    approvals.create_pending(
        thread_id="t3", ticket_id="INC0012354", severity="medium",
        issue_type="network_latency", action="scale_out",
        target="vpn-auth-service", reason="needs approval",
    )
    incident_log.record(
        thread_id="t3", ticket_id="INC0012354", title="VPN throughput degraded",
        severity="medium", issue_type="network_latency", route="await_approval",
        decision="pending_approval", reason="needs approval",
    )


def test_dashboard_loads_without_exceptions(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)

    at = AppTest.from_file(DASHBOARD_PATH)
    at.run()

    assert not at.exception


def test_dashboard_shows_correct_metrics(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)

    at = AppTest.from_file(DASHBOARD_PATH)
    at.run()

    metric_values = {m.label: m.value for m in at.metric}
    assert metric_values["Auto-remediated"] == "1"
    assert metric_values["Escalated"] == "1"
    assert metric_values["Pending approval"] == "1"


def test_dashboard_shows_pending_approval_with_approve_button(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)

    at = AppTest.from_file(DASHBOARD_PATH)
    at.run()

    assert any("INC0012354" in md.value for md in at.markdown)
    assert any(b.label == "Approve" for b in at.button)


def test_dashboard_handles_empty_state_without_exceptions(tmp_path, monkeypatch):
    """No seeded data at all — first run, nothing processed yet."""
    monkeypatch.setattr(approvals, "DB_PATH", tmp_path / "test_approvals.db")
    monkeypatch.setattr(incident_log, "DB_PATH", tmp_path / "test_incidents.db")

    at = AppTest.from_file(DASHBOARD_PATH)
    at.run()

    assert not at.exception
