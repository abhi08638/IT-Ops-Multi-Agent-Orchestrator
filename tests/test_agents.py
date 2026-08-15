"""Unit tests for the three orchestrator agent nodes.

Uses a FakeMCPTools stub instead of a real MCP subprocess connection, so
these tests are fast and deterministic. The real MCP server is exercised
separately via a live end-to-end check (see the PR description / the
project's established live-verification pattern for the MCP tools).
"""

import pytest

from agents import IntakeAgent, RemediationAgent, TriageAgent, classify_issue_type
from state import IncidentState

from conftest import CRITICAL_TICKET, LOW_SEVERITY_TICKET, UNCLASSIFIABLE_TICKET, FakeMCPTools


# --- classify_issue_type -----------------------------------------------

def test_classify_issue_type_matches_service_down():
    assert classify_issue_type(CRITICAL_TICKET) == "service_down"


def test_classify_issue_type_matches_via_error_code():
    assert classify_issue_type(LOW_SEVERITY_TICKET) == "service_down"


def test_classify_issue_type_returns_none_when_no_keywords_match():
    assert classify_issue_type(UNCLASSIFIABLE_TICKET) is None


def test_classify_issue_type_does_not_false_match_substrings():
    """Regression test: 'down' must not match inside 'downstream', and
    'load' must not match inside 'loading' -- found via a live sweep
    across the seed tickets (INC0012349, INC0012351) before this fix."""
    downstream_ticket = {
        "title": "Outbound email delayed",
        "description": "Gateway logs show repeated connection timeouts to the downstream relay.",
    }
    assert classify_issue_type(downstream_ticket) == "network_latency"  # not service_down

    loading_ticket = {
        "title": "Checkout page CSS not loading for some users",
        "description": "CDN cache-busting issue after the latest deploy.",
    }
    assert classify_issue_type(loading_ticket) is None  # not high_cpu


# --- IntakeAgent ---------------------------------------------------------

@pytest.mark.asyncio
async def test_intake_agent_populates_ticket_and_severity():
    tools = FakeMCPTools(tickets={"INC0012345": CRITICAL_TICKET})
    state = IncidentState(ticket_id="INC0012345")

    state = await IntakeAgent(tools).run(state)

    assert state.ticket == CRITICAL_TICKET
    assert state.severity == "critical"
    assert any("Intake" in line for line in state.log)


# --- TriageAgent -----------------------------------------------------------

@pytest.mark.asyncio
async def test_triage_agent_finds_matching_runbook():
    tools = FakeMCPTools(runbooks={"service_down": "# Runbook: Service Down\n..."})
    state = IncidentState(ticket_id="INC0012345", ticket=CRITICAL_TICKET, severity="critical")

    state = await TriageAgent(tools).run(state)

    assert state.issue_type == "service_down"
    assert state.runbook == "# Runbook: Service Down\n..."


@pytest.mark.asyncio
async def test_triage_agent_handles_unclassifiable_ticket_without_crashing():
    tools = FakeMCPTools()
    state = IncidentState(
        ticket_id="INC9999999", ticket=UNCLASSIFIABLE_TICKET, severity="medium"
    )

    state = await TriageAgent(tools).run(state)

    assert state.issue_type is None
    assert state.runbook is None


@pytest.mark.asyncio
async def test_triage_agent_handles_missing_runbook_without_crashing():
    # issue_type classifies fine, but no runbook file exists for it
    tools = FakeMCPTools(runbooks={})
    state = IncidentState(ticket_id="INC0012345", ticket=CRITICAL_TICKET, severity="critical")

    state = await TriageAgent(tools).run(state)

    assert state.issue_type == "service_down"
    assert state.runbook is None
    assert any("no matching runbook" in line for line in state.log)


@pytest.mark.asyncio
async def test_triage_agent_requires_intake_to_have_run_first():
    tools = FakeMCPTools()
    state = IncidentState(ticket_id="INC0012345")  # ticket is None

    with pytest.raises(ValueError):
        await TriageAgent(tools).run(state)


# --- RemediationAgent -------------------------------------------------

@pytest.mark.asyncio
async def test_remediation_agent_auto_remediates_low_severity_known_issue():
    tools = FakeMCPTools()
    state = IncidentState(
        ticket_id="INC0012346",
        ticket=LOW_SEVERITY_TICKET,
        severity="low",
        issue_type="service_down",
    )

    state = await RemediationAgent(tools).run(state)

    assert state.decision == "auto_remediated"
    assert state.remediation_result is not None
    assert tools.run_remediation_calls == [("restart_service", "vpn-auth-service")]


@pytest.mark.asyncio
async def test_remediation_agent_escalates_high_severity_instead_of_executing():
    tools = FakeMCPTools()
    state = IncidentState(
        ticket_id="INC0012345",
        ticket=CRITICAL_TICKET,
        severity="critical",
        issue_type="service_down",
    )

    state = await RemediationAgent(tools).run(state)

    assert state.decision == "escalated"
    assert state.escalation_reason is not None
    assert tools.run_remediation_calls == []  # never actually executed


@pytest.mark.asyncio
async def test_remediation_agent_escalates_unclassified_issue_even_at_low_severity():
    """Defensive case: severity alone doesn't authorize auto-remediation
    if there's no known safe action for the issue type."""
    tools = FakeMCPTools()
    state = IncidentState(
        ticket_id="INC9999999",
        ticket=UNCLASSIFIABLE_TICKET,
        severity="low",
        issue_type=None,
    )

    state = await RemediationAgent(tools).run(state)

    assert state.decision == "escalated"
    assert tools.run_remediation_calls == []


# --- Full pipeline (fakes only) -----------------------------------------

@pytest.mark.asyncio
async def test_full_pipeline_auto_remediates_low_severity_ticket():
    tools = FakeMCPTools(
        tickets={"INC0012346": LOW_SEVERITY_TICKET},
        runbooks={"service_down": "# Runbook: Service Down\n..."},
    )
    state = IncidentState(ticket_id="INC0012346")

    state = await IntakeAgent(tools).run(state)
    state = await TriageAgent(tools).run(state)
    state = await RemediationAgent(tools).run(state)

    assert state.decision == "auto_remediated"
    assert len(state.log) == 3  # one entry per agent


@pytest.mark.asyncio
async def test_full_pipeline_escalates_critical_ticket():
    tools = FakeMCPTools(
        tickets={"INC0012345": CRITICAL_TICKET},
        runbooks={"service_down": "# Runbook: Service Down\n..."},
    )
    state = IncidentState(ticket_id="INC0012345")

    state = await IntakeAgent(tools).run(state)
    state = await TriageAgent(tools).run(state)
    state = await RemediationAgent(tools).run(state)

    assert state.decision == "escalated"
    assert tools.run_remediation_calls == []
