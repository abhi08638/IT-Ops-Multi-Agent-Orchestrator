"""orchestrator/graph.py — LangGraph StateGraph wiring the agent nodes
together with a supervisor that routes to remediation or escalation.

    intake -> triage -> supervisor --(remediate)--> remediation -> END
                                   \\-(escalate)---> escalation  -> END

The supervisor node makes no MCP calls itself — it only calls the pure
decide_route() function (also used by RemediationAgent/EscalationAgent)
to pick a branch based on the shared IncidentState. Each node wraps the
existing Agent classes from agents.py, so the decision/execution logic
lives in exactly one place regardless of whether it's driven by this
graph or the manual chaining in run_demo.py.
"""

from langgraph.graph import END, START, StateGraph

from agents import EscalationAgent, IntakeAgent, RemediationAgent, TriageAgent, decide_route
from mcp_client import MCPTools
from state import IncidentState


def build_graph(tools: MCPTools):
    """Build and compile the StateGraph for one MCPTools connection."""
    graph = StateGraph(IncidentState)

    async def intake_node(state: IncidentState) -> dict:
        updated = await IntakeAgent(tools).run(state)
        return {"ticket": updated.ticket, "severity": updated.severity, "log": updated.log}

    async def triage_node(state: IncidentState) -> dict:
        updated = await TriageAgent(tools).run(state)
        return {
            "issue_type": updated.issue_type,
            "runbook": updated.runbook,
            "log": updated.log,
        }

    async def supervisor_node(state: IncidentState) -> dict:
        route, action, reason = decide_route(state)
        detail = reason if route == "escalate" else f"proposed action={action!r}"
        return {
            "route": route,
            "log": state.log + [f"Supervisor: routing to {route!r} ({detail})"],
        }

    async def remediation_node(state: IncidentState) -> dict:
        updated = await RemediationAgent(tools).run(state)
        return {
            "decision": updated.decision,
            "remediation_result": updated.remediation_result,
            "log": updated.log,
        }

    async def escalation_node(state: IncidentState) -> dict:
        updated = await EscalationAgent(tools).run(state)
        return {
            "decision": updated.decision,
            "escalation_reason": updated.escalation_reason,
            "log": updated.log,
        }

    graph.add_node("intake", intake_node)
    graph.add_node("triage", triage_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("remediation", remediation_node)
    graph.add_node("escalation", escalation_node)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "triage")
    graph.add_edge("triage", "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        lambda state: state.route,
        {"remediate": "remediation", "escalate": "escalation"},
    )
    graph.add_edge("remediation", END)
    graph.add_edge("escalation", END)

    return graph.compile()


async def run_incident(tools: MCPTools, ticket_id: str) -> IncidentState:
    """Run one ticket through the compiled graph and return the final
    IncidentState (ainvoke() returns a plain dict even for a dataclass
    state schema, so this reconstructs the dataclass for convenience)."""
    app = build_graph(tools)
    result = await app.ainvoke(IncidentState(ticket_id=ticket_id))
    return IncidentState(**result)
