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

import re
from abc import ABC, abstractmethod
from typing import NamedTuple

from mcp_client import MCPTools, RunbookNotFoundError
from state import IncidentState
from tracing import traced_agent, traced_decision

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


def _contains_word(haystack: str, keyword: str) -> bool:
    """Whole-word/phrase match, not substring containment.

    Plain `kw in haystack` would match "down" inside "downstream" or
    "load" inside "loading" — both real false positives found in the
    seed data (INC0012349's "downstream relay" misclassified as
    service_down; INC0012351's "CSS not loading" misclassified as
    high_cpu). \\b word boundaries fix both without needing an
    exceptions list.
    """
    return re.search(rf"\b{re.escape(keyword)}\b", haystack) is not None


def classify_issue_type(ticket: dict) -> str | None:
    """Best-effort keyword classification of a ticket into a known
    runbook issue_type. Returns None if nothing scores above zero,
    rather than guessing."""
    haystack = f"{ticket.get('title', '')} {ticket.get('description', '')}".lower()
    scores = {
        issue_type: sum(1 for kw in keywords if _contains_word(haystack, kw))
        for issue_type, keywords in _ISSUE_TYPE_KEYWORDS.items()
    }
    best_issue_type, best_score = max(scores.items(), key=lambda pair: pair[1])
    return best_issue_type if best_score > 0 else None


class RouteDecision(NamedTuple):
    route: str  # "remediate" | "escalate"
    action: str | None  # proposed/executed action, e.g. 'restart_service'
    target: str  # the ticket's affected_system, or "unknown"
    reason: str | None  # set only when route == "escalate"


@traced_decision("supervisor_decide_route")
def decide_route(state: IncidentState) -> RouteDecision:
    """Decide whether an incident should be auto-remediated or escalated.

    Pure function, no I/O — this is the single source of truth for the
    routing decision, used by both the graph's supervisor node (to pick
    an edge) and RemediationAgent/EscalationAgent (to act on it). A
    known safe action AND a low/medium severity are both required to
    remediate; anything else escalates.
    """
    action = _ACTION_BY_ISSUE_TYPE.get(state.issue_type) if state.issue_type else None
    target = (state.ticket or {}).get("affected_system", "unknown")

    if action is None:
        reason = f"No known safe remediation action for issue_type={state.issue_type!r}"
        return RouteDecision("escalate", None, target, reason)

    if state.severity not in AUTO_REMEDIATE_SEVERITIES:
        reason = (
            f"Severity {state.severity!r} requires human approval before "
            f"remediation (proposed action: {action!r} on {target!r})"
        )
        return RouteDecision("escalate", action, target, reason)

    return RouteDecision("remediate", action, target, None)


class Agent(ABC):
    """Common interface for a pipeline node: takes state, returns state."""

    def __init__(self, tools: MCPTools):
        self.tools = tools

    @abstractmethod
    async def run(self, state: IncidentState) -> IncidentState:
        ...


class IntakeAgent(Agent):
    """Pulls a ticket via the check_ticket MCP tool and seeds the state."""

    @traced_agent("intake_agent")
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

    @traced_agent("triage_agent")
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
    tickets with a known safe action, otherwise escalates.

    Standalone use (manual chaining, see run_demo.py): decides AND acts.
    In the LangGraph pipeline (graph.py), the supervisor node has
    already made this same decision via decide_route() before routing
    here — this agent re-derives it (a cheap, pure, deterministic call)
    rather than trusting the router blindly, and only ever executes on
    the "remediate" branch.
    """

    @traced_agent("remediation_agent")
    async def run(self, state: IncidentState) -> IncidentState:
        decision = decide_route(state)

        if decision.route == "escalate":
            state.decision = "escalated"
            state.escalation_reason = decision.reason
            state.log.append(f"Remediation: {decision.reason}")
            return state

        result = await self.tools.run_remediation(decision.action, decision.target)
        state.decision = "auto_remediated"
        state.remediation_result = result
        state.log.append(
            f"Remediation: severity={state.severity!r} -> auto-executed "
            f"action={decision.action!r} on target={decision.target!r}"
        )
        return state


class EscalationAgent(Agent):
    """Marks an incident as escalated for human review.

    Used on the graph's escalate branch, after the supervisor has
    already routed here — this agent never calls run_remediation. It
    re-derives the reason via decide_route() purely to produce the
    human-readable explanation; it always escalates unconditionally,
    since being invoked on this branch is itself the routing decision.
    """

    @traced_agent("escalation_agent")
    async def run(self, state: IncidentState) -> IncidentState:
        decision = decide_route(state)
        state.decision = "escalated"
        state.escalation_reason = decision.reason or "Escalated for human review."
        state.log.append(f"Escalation: {state.escalation_reason}")
        return state
