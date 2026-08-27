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
from datetime import datetime
from pathlib import Path

from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))

import approvals
import incident_log

DASHBOARD_PATH = str(Path(__file__).resolve().parent.parent / "dashboard" / "app.py")


def _table_html(at) -> str:
    """The Recent Tickets table is hand-rolled HTML via st.markdown (not
    st.table/st.dataframe), so find it among the other st.markdown calls
    (e.g. the pending-approval cards) by looking for the <table> tag."""
    for md in at.markdown:
        if "<table" in md.value:
            return md.value
    raise AssertionError("Recent Tickets table not found in markdown output")


def _seed(tmp_path, monkeypatch):
    monkeypatch.setattr(approvals, "DB_PATH", tmp_path / "test_approvals.db")
    monkeypatch.setattr(incident_log, "DB_PATH", tmp_path / "test_incidents.db")
    approvals.init_db()
    incident_log.init_db()

    incident_log.record(
        thread_id="t1", ticket_id="INC0012346", title="VPN password reset",
        severity="low", issue_type="service_down", route="remediate",
        decision="auto_remediated", reason=None,
        action="restart_service", target="vpn-auth-service",
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


def test_dashboard_table_shows_realistic_action_not_the_decision_code(tmp_path, monkeypatch):
    """Regression test: 'Action Taken' must be a specific, realistic
    description (e.g. 'Restarted service on vpn-auth-service'), not
    just a repeat of the Decision column ('Auto-remediated') and not a
    raw snake_case code."""
    _seed(tmp_path, monkeypatch)

    at = AppTest.from_file(DASHBOARD_PATH)
    at.run()

    table_html = _table_html(at)

    assert "Restarted service on vpn-auth-service" in table_html
    assert "restart_service" not in table_html  # no leftover snake_case action code
    # rows with nothing actually executed show a placeholder, not a
    # fabricated action -- INC0012354 (pending) and INC0012345 (escalated)
    assert table_html.count(">—<") >= 2


def test_dashboard_table_humanizes_severity_and_issue_type(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)

    at = AppTest.from_file(DASHBOARD_PATH)
    at.run()

    table_html = _table_html(at)

    assert "Medium" in table_html
    assert "Network Latency" in table_html
    assert "network_latency" not in table_html
    assert "Pending Approval" in table_html


def test_dashboard_table_shows_reason_as_tooltip_on_escalated_row(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)

    at = AppTest.from_file(DASHBOARD_PATH)
    at.run()

    table_html = _table_html(at)

    assert "title='too risky'" in table_html
    assert "cursor: help" in table_html


def test_dashboard_table_no_tooltip_for_rows_without_a_reason(tmp_path, monkeypatch):
    """INC0012346 is auto_remediated with reason=None -- its Decision
    cell must be plain text, not wrapped in a tooltip span."""
    _seed(tmp_path, monkeypatch)

    at = AppTest.from_file(DASHBOARD_PATH)
    at.run()

    table_html = _table_html(at)

    assert "<td style='padding:4px 10px;'>Auto-remediated</td>" in table_html


def test_dashboard_table_shows_updated_time_in_local_12_hour_format(tmp_path, monkeypatch):
    """The Updated column shows local time as MM/DD/YYYY HH:MM:SS AM/PM,
    not the raw stored UTC ISO string."""
    _seed(tmp_path, monkeypatch)

    stored = incident_log.list_recent(limit=20)
    row = next(r for r in stored if r["ticket_id"] == "INC0012346")
    expected = datetime.fromisoformat(row["updated_at"]).astimezone().strftime("%m/%d/%Y %I:%M:%S %p")

    at = AppTest.from_file(DASHBOARD_PATH)
    at.run()

    table_html = _table_html(at)
    assert expected in table_html
    assert row["updated_at"] not in table_html  # raw ISO string shouldn't leak through


def test_dashboard_handles_empty_state_without_exceptions(tmp_path, monkeypatch):
    """No seeded data at all — first run, nothing processed yet."""
    monkeypatch.setattr(approvals, "DB_PATH", tmp_path / "test_approvals.db")
    monkeypatch.setattr(incident_log, "DB_PATH", tmp_path / "test_incidents.db")

    at = AppTest.from_file(DASHBOARD_PATH)
    at.run()

    assert not at.exception
