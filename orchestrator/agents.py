"""orchestrator/agents.py — the three IT Ops agent nodes.

Each agent is a small class with an async run(state) -> state method,
so a future orchestrator can just chain them, reusing one MCP session
across the whole pipeline:

    async with mcp_tools_session() as tools:
        state = IncidentState(ticket_id="INC0012345")
        state = await IntakeAgent(tools).run(state)
        state = await TriageAgent(tools).run(state)
        state = await RemediationAgent(tools).run(state)
"""

from abc import ABC, abstractmethod

from mcp_client import MCPTools, RunbookNotFoundError
from state import IncidentState

# Severities that are safe to auto-remediate without a human in the loop.
# Anything else (high/critical, or an unrecognized value) escalates.
AUTO_REMEDIATE_SEVERITIES = {"low", "medium"}

# Best-effort keyword -> issue_type classifier. Real classification would
# likely be an LLM call or a trained model; this is a deterministic
# stand-in so Triage stays fast and unit-testable without a live API call.
_ISSUE_TYPE_KEYWORDS = {
    "high_cpu": ("cpu", "load", "processor", "utilization"),
    "service_down": (
        "unresponsive", "down", "outage", "crash", "not responding", "502", "500",
    ),
    "disk_full": ("disk", "space", "storage"),
    "network_latency": ("latency", "slow", "throughput", "vpn", "connection"),
}

# Canonical remediation action for each known issue type. Anything not
# in this map has no known safe automated fix, so it always escalates,
# regardless of severity.
_ACTION_BY_ISSUE_TYPE = {
    "high_cpu": "restart_service",
    "service_down": "restart_service",
    "disk_full": "clear_disk_space",
    "network_latency": "scale_out",
}


def classify_issue_type(ticket: dict) -> str | None:
    """Best-effort keyword classification of a ticket into a known
    runbook issue_type. Returns None if nothing scores above zero,
    rather than guessing."""
    haystack = f"{ticket.get('title', '')} {ticket.get('description', '')}".lower()
    scores = {
        issue_type: sum(1 for kw in keywords if kw in haystack)
        for issue_type, keywords in _ISSUE_TYPE_KEYWORDS.items()
    }
    best_issue_type, best_score = max(scores.items(), key=lambda pair: pair[1])
    return best_issue_type if best_score > 0 else None


class Agent(ABC):
    """Common interface for a pipeline node: takes state, returns state."""

    def __init__(self, tools: MCPTools):
        self.tools = tools

    @abstractmethod
    async def run(self, state: IncidentState) -> IncidentState:
        ...


class IntakeAgent(Agent):
    """Pulls a ticket via the check_ticket MCP tool and seeds the state."""

    async def run(self, state: IncidentState) -> IncidentState:
        ticket = await self.tools.check_ticket(state.ticket_id)
        state.ticket = ticket
        state.severity = ticket.get("severity")
        state.log.append(
            f"Intake: pulled ticket {state.ticket_id} "
            f"(severity={state.severity}, system={ticket.get('affected_system')})"
        )
        return state


class TriageAgent(Agent):
    """Classifies issue_type and fetches the matching runbook, if any."""

    async def run(self, state: IncidentState) -> IncidentState:
        if state.ticket is None:
            raise ValueError("TriageAgent requires state.ticket — run IntakeAgent first")

        issue_type = classify_issue_type(state.ticket)
        state.issue_type = issue_type

        if issue_type is None:
            state.log.append(
                "Triage: could not classify a known issue_type from the ticket text"
            )
            return state

        try:
            state.runbook = await self.tools.get_runbook(issue_type)
            state.log.append(f"Triage: classified issue_type={issue_type!r}; runbook found")
        except RunbookNotFoundError:
            state.log.append(
                f"Triage: classified issue_type={issue_type!r}, "
                "but no matching runbook exists"
            )
        return state


class RemediationAgent(Agent):
    """Proposes a remediation action; auto-executes it for low-severity
    tickets with a known safe action, otherwise escalates."""

    async def run(self, state: IncidentState) -> IncidentState:
        action = _ACTION_BY_ISSUE_TYPE.get(state.issue_type) if state.issue_type else None
        target = (state.ticket or {}).get("affected_system", "unknown")

        if action is None:
            state.decision = "escalated"
            state.escalation_reason = (
                f"No known safe remediation action for issue_type={state.issue_type!r}"
            )
            state.log.append(f"Remediation: {state.escalation_reason}")
            return state

        if state.severity not in AUTO_REMEDIATE_SEVERITIES:
            state.decision = "escalated"
            state.escalation_reason = (
                f"Severity {state.severity!r} requires human approval before "
                f"remediation (proposed action: {action!r} on {target!r})"
            )
            state.log.append(f"Remediation: {state.escalation_reason}")
            return state

        result = await self.tools.run_remediation(action, target)
        state.decision = "auto_remediated"
        state.remediation_result = result
        state.log.append(
            f"Remediation: severity={state.severity!r} -> auto-executed "
            f"action={action!r} on target={target!r}"
        )
        return state
