"""Unit tests for the LangGraph StateGraph in orchestrator/graph.py.

Uses a FakeMCPTools stub instead of a real MCP subprocess connection —
same approach as tests/test_agents.py, so these tests are fast and
deterministic. The real MCP server + real graph.ainvoke() is exercised
separately via a live end-to-end check.
"""

import pytest

from graph import run_incident

from conftest import CRITICAL_TICKET, LOW_SEVERITY_TICKET, UNCLASSIFIABLE_TICKET, FakeMCPTools


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
