"""Unit tests for incident_log.py — the durable per-thread incident feed."""

import incident_log


def _use_temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(incident_log, "DB_PATH", tmp_path / "test_incidents.db")
    incident_log.init_db()


def test_record_appears_in_list_recent(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    incident_log.record(
        thread_id="t1", ticket_id="INC0012346", title="VPN password reset",
        severity="low", issue_type="service_down", route="remediate",
        decision="auto_remediated", reason=None,
    )

    recent = incident_log.list_recent()
    assert len(recent) == 1
    assert recent[0]["ticket_id"] == "INC0012346"
    assert recent[0]["decision"] == "auto_remediated"


def test_record_upserts_by_thread_id_rather_than_duplicating(tmp_path, monkeypatch):
    """A pending_approval row later gets updated in place to
    auto_remediated once resumed -- not inserted as a second row."""
    _use_temp_db(tmp_path, monkeypatch)

    incident_log.record(
        thread_id="t1", ticket_id="INC0012354", title="VPN throughput degraded",
        severity="medium", issue_type="network_latency", route="await_approval",
        decision="pending_approval", reason="needs approval",
    )
    incident_log.record(
        thread_id="t1", ticket_id="INC0012354", title="VPN throughput degraded",
        severity="medium", issue_type="network_latency", route="await_approval",
        decision="auto_remediated", reason="needs approval",
    )

    recent = incident_log.list_recent()
    assert len(recent) == 1
    assert recent[0]["decision"] == "auto_remediated"


def test_count_by_decision(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    incident_log.record(
        thread_id="t1", ticket_id="INC1", title="a", severity="low",
        issue_type="service_down", route="remediate", decision="auto_remediated", reason=None,
    )
    incident_log.record(
        thread_id="t2", ticket_id="INC2", title="b", severity="critical",
        issue_type="service_down", route="escalate", decision="escalated", reason="too risky",
    )
    incident_log.record(
        thread_id="t3", ticket_id="INC3", title="c", severity="critical",
        issue_type="service_down", route="escalate", decision="escalated", reason="too risky",
    )

    counts = incident_log.count_by_decision()
    assert counts == {"auto_remediated": 1, "escalated": 2}


def test_list_recent_respects_limit(tmp_path, monkeypatch):
    _use_temp_db(tmp_path, monkeypatch)

    for i in range(5):
        incident_log.record(
            thread_id=f"t{i}", ticket_id=f"INC{i}", title="x", severity="low",
            issue_type="service_down", route="remediate", decision="auto_remediated", reason=None,
        )

    assert len(incident_log.list_recent(limit=3)) == 3
    assert len(incident_log.list_recent(limit=20)) == 5
