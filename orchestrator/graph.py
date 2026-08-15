"""orchestrator/graph.py — LangGraph StateGraph wiring the agent nodes
together with a supervisor that routes to remediation or escalation.

    intake -> triage -> supervisor --(remediate)--> remediation -> END
                                   \\-(escalate)---> escalation  -> END

The supervisor node makes no MCP calls itself — it only calls the pure
decide_route() function (also used by RemediationAgent/EscalationAgent)
to pick a branch based on the shared IncidentState. Each other node
wraps an existing Agent class from agents.py, so the decision/execution
logic lives in exactly one place regardless of whether it's driven by
this graph or the manual chaining in run_demo.py.
"""

from dataclasses import asdict

from langgraph.graph import END, START, StateGraph

from agents import Agent, EscalationAgent, IntakeAgent, RemediationAgent, TriageAgent, decide_route
from mcp_client import MCPTools
from state import IncidentState


def _agent_node(agent_cls: type[Agent], tools: MCPTools):
    """Wrap an Agent subclass as a LangGraph node.

    Runs the agent and hands back its *entire* updated state as the
    node's output — LangGraph merges the returned dict into the shared
    state, so this is equivalent to (and simpler than) hand-picking
    just the fields each agent happens to touch.
    """

    async def node(state: IncidentState) -> dict:
        updated = await agent_cls(tools).run(state)
        return asdict(updated)

    return node


def build_graph(tools: MCPTools):
    """Build and compile the StateGraph for one MCPTools connection."""
    graph = StateGraph(IncidentState)

    async def supervisor_node(state: IncidentState) -> dict:
        decision = decide_route(state)
        detail = decision.reason if decision.route == "escalate" else f"proposed action={decision.action!r}"
        return {
            "route": decision.route,
            "log": state.log + [f"Supervisor: routing to {decision.route!r} ({detail})"],
        }

    graph.add_node("intake", _agent_node(IntakeAgent, tools))
    graph.add_node("triage", _agent_node(TriageAgent, tools))
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("remediation", _agent_node(RemediationAgent, tools))
    graph.add_node("escalation", _agent_node(EscalationAgent, tools))

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
