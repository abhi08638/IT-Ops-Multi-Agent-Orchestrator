"""orchestrator/graph.py — LangGraph StateGraph wiring the agent nodes
together with a supervisor that routes to remediation, a hard approval
gate, or escalation.

    intake -> triage -> supervisor --(remediate)-------> remediation    -> END
                                   |-(await_approval)---> approval_gate -> END
                                   \\-(escalate)---------> escalation    -> END

The supervisor node makes no MCP calls itself — it only calls the pure
decide_route() function (also used by RemediationAgent/EscalationAgent/
approval_gate_node) to pick a branch based on the shared IncidentState.

approval_gate_node is where the hard approval gate actually lives: for
medium-severity tickets with a known action, it records a pending
approval (see approvals.py) and calls interrupt() — LangGraph persists
the paused state via the checkpointer and ainvoke() returns without
completing. A later call to resume_incident() (from the dashboard, in a
separate process) reconnects to the same checkpoint file, resumes that
exact thread, and — if approved — runs the real run_remediation call
that was withheld the first time around.
"""

import dataclasses
import uuid
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

import approvals
import incident_log
from agents import Agent, EscalationAgent, IntakeAgent, RemediationAgent, TriageAgent, decide_route
from mcp_client import MCPTools
from state import IncidentState
from tracing import traced_agent

CHECKPOINT_DB_PATH = Path(__file__).resolve().parent / "checkpoints.db"

_STATE_FIELDS = {f.name for f in dataclasses.fields(IncidentState)}


def _agent_node(agent_cls: type[Agent], tools: MCPTools):
    """Wrap an Agent subclass as a LangGraph node.

    Runs the agent and hands back its *entire* updated state as the
    node's output — LangGraph merges the returned dict into the shared
    state, so this is equivalent to (and simpler than) hand-picking
    just the fields each agent happens to touch.
    """

    async def node(state: IncidentState) -> dict:
        updated = await agent_cls(tools).run(state)
        return dataclasses.asdict(updated)

    return node


def build_graph(tools: MCPTools, checkpointer):
    """Build and compile the StateGraph for one MCPTools connection.

    checkpointer is passed in explicitly (rather than hardcoded) so
    tests can use a fast in-memory one while run_incident/resume_incident
    use a real persistent SQLite one — a paused thread has to survive
    past the end of the process that created it, since the dashboard
    resumes it later from a separate process.
    """
    graph = StateGraph(IncidentState)

    @traced_agent("supervisor")
    async def supervisor_node(state: IncidentState) -> dict:
        decision = decide_route(state)
        detail = decision.reason if decision.route != "remediate" else f"proposed action={decision.action!r}"
        return {
            "route": decision.route,
            "log": state.log + [f"Supervisor: routing to {decision.route!r} ({detail})"],
        }

    @traced_agent("approval_gate")
    async def approval_gate_node(state: IncidentState, config: RunnableConfig) -> dict:
        decision = decide_route(state)
        thread_id = config["configurable"]["thread_id"]

        approvals.create_pending(
            thread_id=thread_id,
            ticket_id=state.ticket_id,
            severity=state.severity,
            issue_type=state.issue_type,
            action=decision.action,
            target=decision.target,
            reason=decision.reason,
        )

        # Pauses here on first entry -- everything below only runs once
        # the dashboard resumes this thread with Command(resume=...).
        approved: bool = interrupt(
            {
                "ticket_id": state.ticket_id,
                "severity": state.severity,
                "action": decision.action,
                "target": decision.target,
                "reason": decision.reason,
            }
        )

        if not approved:
            approvals.mark_decided(thread_id, "rejected")
            return {
                "decision": "escalated",
                "escalation_reason": decision.reason,
                "log": state.log + ["Approval Gate: rejected -- escalating instead"],
            }

        result = await tools.run_remediation(decision.action, decision.target)
        approvals.mark_decided(thread_id, "approved")
        return {
            "decision": "auto_remediated",
            "remediation_result": result,
            "log": state.log + [
                f"Approval Gate: approved -> auto-executed action={decision.action!r} "
                f"on target={decision.target!r}"
            ],
        }

    graph.add_node("intake", _agent_node(IntakeAgent, tools))
    graph.add_node("triage", _agent_node(TriageAgent, tools))
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("remediation", _agent_node(RemediationAgent, tools))
    graph.add_node("approval_gate", approval_gate_node)
    graph.add_node("escalation", _agent_node(EscalationAgent, tools))

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "triage")
    graph.add_edge("triage", "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        lambda state: state.route,
        {
            "remediate": "remediation",
            "await_approval": "approval_gate",
            "escalate": "escalation",
        },
    )
    graph.add_edge("remediation", END)
    graph.add_edge("approval_gate", END)
    graph.add_edge("escalation", END)

    return graph.compile(checkpointer=checkpointer)


def _state_from_result(result: dict, ticket_id: str) -> IncidentState:
    """ainvoke() returns a plain dict even for a dataclass state schema
    (confirmed empirically) — reconstruct IncidentState, stripping
    LangGraph-internal keys like '__interrupt__' that aren't part of
    our schema.

    A paused run's result has route='await_approval' (set by
    supervisor_node, which did complete) but decision=None (the
    approval_gate node's return never executed, since it's paused
    mid-function at the interrupt() call) — so decision is filled in
    here explicitly as 'pending_approval' whenever '__interrupt__' is
    present, rather than left as a misleading None.
    """
    is_paused = "__interrupt__" in result
    clean = {k: v for k, v in result.items() if k in _STATE_FIELDS}
    clean.setdefault("ticket_id", ticket_id)
    state = IncidentState(**clean)
    if is_paused:
        state.decision = "pending_approval"
    return state


def _record(state: IncidentState, thread_id: str) -> None:
    incident_log.record(
        thread_id=thread_id,
        ticket_id=state.ticket_id,
        title=(state.ticket or {}).get("title"),
        severity=state.severity,
        issue_type=state.issue_type,
        route=state.route,
        decision=state.decision or "unknown",
        reason=state.escalation_reason,
    )


async def run_incident(tools: MCPTools, ticket_id: str) -> IncidentState:
    """Run one ticket through the compiled graph from the start.

    Returns the resulting IncidentState — check state.decision:
    'pending_approval' means it paused at the approval gate (see
    approvals.list_pending() / resume_incident()); 'auto_remediated' or
    'escalated' means it's fully done.
    """
    approvals.init_db()
    incident_log.init_db()

    thread_id = f"{ticket_id}-{uuid.uuid4().hex[:8]}"
    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB_PATH)) as checkpointer:
        app = build_graph(tools, checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        result = await app.ainvoke(IncidentState(ticket_id=ticket_id), config=config)

    state = _state_from_result(result, ticket_id)
    _record(state, thread_id)
    return state


async def resume_incident(
    tools: MCPTools, thread_id: str, ticket_id: str, approved: bool
) -> IncidentState:
    """Resume a thread paused at the approval gate (called by the
    dashboard's Approve action, from a separate process than the one
    that started the run — that's why this reconnects to the checkpoint
    file rather than holding a graph object across calls)."""
    approvals.init_db()
    incident_log.init_db()

    async with AsyncSqliteSaver.from_conn_string(str(CHECKPOINT_DB_PATH)) as checkpointer:
        app = build_graph(tools, checkpointer)
        config = {"configurable": {"thread_id": thread_id}}
        result = await app.ainvoke(Command(resume=approved), config=config)

    state = _state_from_result(result, ticket_id)
    _record(state, thread_id)
    return state
