"""Unit tests for the LangGraph StateGraph in orchestrator/graph.py.

Uses a FakeMCPTools stub instead of a real MCP subprocess connection —
same approach as tests/test_agents.py, so these tests are fast and
deterministic. The real MCP server + real graph.ainvoke() (including a
real pause/resume cycle) is exercised separately via a live end-to-end
check.
"""

import pytest

import approvals
import graph
import incident_log
from graph import resume_incident, run_incident

from conftest import (
    CRITICAL_TICKET,
    LOW_SEVERITY_TICKET,
    MEDIUM_SEVERITY_TICKET,
    UNCLASSIFIABLE_TICKET,
    FakeMCPTools,
)


@pytest.fixture(autouse=True)
def _isolated_stores(tmp_path, monkeypatch):
    """Every test in this file gets its own temp checkpoint/approvals/
    incidents DBs, never the real orchestrator/*.db files."""
    monkeypatch.setattr(graph, "CHECKPOINT_DB_PATH", tmp_path / "test_checkpoints.db")
    monkeypatch.setattr(approvals, "DB_PATH", tmp_path / "test_approvals.db")
    monkeypatch.setattr(incident_log, "DB_PATH", tmp_path / "test_incidents.db")


@pytest.mark.asyncio
async def test_graph_routes_low_severity_to_remediation():
    tools = FakeMCPTools(
        tickets={"INC0012346": LOW_SEVERITY_TICKET},
        runbooks={"service_down": "# Runbook: Service Down\n..."},
    )

    state = await run_incident(tools, "INC0012346")

    assert state.route == "remediate"
    assert state.decision == "auto_remediated"
    assert state.remediation_result is not None
    assert tools.run_remediation_calls == [("restart_service", "vpn-auth-service")]
    # every node left a trail
    assert any(line.startswith("Intake:") for line in state.log)
    assert any(line.startswith("Triage:") for line in state.log)
    assert any(line.startswith("Supervisor:") for line in state.log)
    assert any(line.startswith("Remediation:") for line in state.log)


@pytest.mark.asyncio
async def test_graph_routes_critical_severity_to_escalation():
    tools = FakeMCPTools(
        tickets={"INC0012345": CRITICAL_TICKET},
        runbooks={"service_down": "# Runbook: Service Down\n..."},
    )

    state = await run_incident(tools, "INC0012345")

    assert state.route == "escalate"
    assert state.decision == "escalated"
    assert state.escalation_reason is not None
    assert tools.run_remediation_calls == []  # never executed
    assert any(line.startswith("Escalation:") for line in state.log)
    assert not any(line.startswith("Remediation:") for line in state.log)


@pytest.mark.asyncio
async def test_graph_escalates_unclassifiable_ticket_even_at_low_severity():
    tools = FakeMCPTools(tickets={"INC9999999": UNCLASSIFIABLE_TICKET})

    state = await run_incident(tools, "INC9999999")

    assert state.issue_type is None
    assert state.route == "escalate"
    assert state.decision == "escalated"
    assert tools.run_remediation_calls == []


@pytest.mark.asyncio
async def test_graph_escalation_branch_never_calls_get_runbook_or_remediation_twice():
    """Sanity check that each branch of the graph runs exactly once —
    e.g. remediation_node isn't accidentally reachable after escalation."""
    tools = FakeMCPTools(
        tickets={"INC0012345": CRITICAL_TICKET},
        runbooks={"service_down": "# Runbook: Service Down\n..."},
    )

    state = await run_incident(tools, "INC0012345")

    # log should have exactly one entry per visited node: intake, triage,
    # supervisor, escalation (remediation is never visited on this branch)
    assert len(state.log) == 4


# --- Hard approval gate: pause + resume ----------------------------------

@pytest.mark.asyncio
async def test_graph_pauses_medium_severity_for_approval():
    tools = FakeMCPTools(
        tickets={"INC0012354": MEDIUM_SEVERITY_TICKET},
        runbooks={"network_latency": "# Runbook: Network Latency\n..."},
    )

    state = await run_incident(tools, "INC0012354")

    assert state.route == "await_approval"
    assert state.decision == "pending_approval"
    assert tools.run_remediation_calls == []  # withheld, not executed

    pending = approvals.list_pending()
    assert len(pending) == 1
    assert pending[0]["ticket_id"] == "INC0012354"
    assert pending[0]["action"] == "scale_out"

    recent = incident_log.list_recent()
    assert len(recent) == 1
    assert recent[0]["decision"] == "pending_approval"


@pytest.mark.asyncio
async def test_resume_approved_executes_and_clears_the_queue():
    tools = FakeMCPTools(
        tickets={"INC0012354": MEDIUM_SEVERITY_TICKET},
        runbooks={"network_latency": "# Runbook: Network Latency\n..."},
    )

    await run_incident(tools, "INC0012354")
    thread_id = approvals.list_pending()[0]["thread_id"]

    resumed = await resume_incident(tools, thread_id, "INC0012354", approved=True)

    assert resumed.decision == "auto_remediated"
    assert resumed.remediation_result is not None
    assert tools.run_remediation_calls == [("scale_out", "vpn-auth-service")]
    assert approvals.list_pending() == []  # no longer pending

    # incident_log row was updated in place, not duplicated
    recent = incident_log.list_recent()
    assert len(recent) == 1
    assert recent[0]["decision"] == "auto_remediated"


@pytest.mark.asyncio
async def test_resume_rejected_escalates_instead_of_executing():
    tools = FakeMCPTools(
        tickets={"INC0012354": MEDIUM_SEVERITY_TICKET},
        runbooks={"network_latency": "# Runbook: Network Latency\n..."},
    )

    await run_incident(tools, "INC0012354")
    thread_id = approvals.list_pending()[0]["thread_id"]

    resumed = await resume_incident(tools, thread_id, "INC0012354", approved=False)

    assert resumed.decision == "escalated"
    assert tools.run_remediation_calls == []  # rejection never executes
    assert approvals.list_pending() == []

    recent = incident_log.list_recent()
    assert recent[0]["decision"] == "escalated"


@pytest.mark.asyncio
async def test_pause_and_resume_use_distinct_thread_ids_per_run():
    """Two separate runs of the same ticket_id shouldn't collide on the
    same paused thread."""
    tools = FakeMCPTools(
        tickets={"INC0012354": MEDIUM_SEVERITY_TICKET},
        runbooks={"network_latency": "# Runbook: Network Latency\n..."},
    )

    await run_incident(tools, "INC0012354")
    await run_incident(tools, "INC0012354")

    assert len(approvals.list_pending()) == 2
