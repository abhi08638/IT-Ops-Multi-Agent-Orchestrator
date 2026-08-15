"""Unit tests for the LangGraph StateGraph in orchestrator/graph.py.

Uses a FakeMCPTools stub instead of a real MCP subprocess connection —
same approach as tests/test_agents.py, so these tests are fast and
deterministic. The real MCP server + real graph.ainvoke() is exercised
separately via a live end-to-end check.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "orchestrator"))

from graph import run_incident
from mcp_client import RunbookNotFoundError


class FakeMCPTools:
    def __init__(self, tickets=None, runbooks=None):
        self.tickets = tickets or {}
        self.runbooks = runbooks or {}
        self.run_remediation_calls = []

    async def check_ticket(self, ticket_id: str) -> dict:
        return self.tickets[ticket_id]

    async def get_runbook(self, issue_type: str) -> str:
        if issue_type not in self.runbooks:
            raise RunbookNotFoundError(f"No runbook found for issue_type={issue_type!r}")
        return self.runbooks[issue_type]

    async def run_remediation(self, action: str, target: str) -> dict:
        self.run_remediation_calls.append((action, target))
        return {
            "id": len(self.run_remediation_calls),
            "status": "simulated",
            "action": action,
            "target": target,
            "message": f"Would run action {action!r} against target {target!r}.",
            "note": "Mock executor — no real command was run.",
        }


CRITICAL_TICKET = {
    "ticket_id": "INC0012345",
    "title": "Production web server unresponsive",
    "description": "Customers report intermittent 502 errors. Health checks failing.",
    "severity": "critical",
    "affected_system": "web-prod-cluster-03",
    "status": "open",
}

LOW_SEVERITY_TICKET = {
    "ticket_id": "INC0012346",
    "title": "User unable to reset VPN password",
    "description": "The self-service password reset portal returns a 500 error.",
    "severity": "low",
    "affected_system": "vpn-auth-service",
    "status": "open",
}

UNCLASSIFIABLE_TICKET = {
    "ticket_id": "INC9999999",
    "title": "Unspecified issue reported",
    "description": "No further detail was provided when the ticket was logged.",
    "severity": "medium",
    "affected_system": "unknown",
    "status": "open",
}


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
