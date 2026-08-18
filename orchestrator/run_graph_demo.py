"""orchestrator/run_graph_demo.py — run the LangGraph StateGraph
(intake -> triage -> supervisor -> remediation / approval_gate /
escalation) against a few sample tickets, against the real MCP server,
and print the decision trail for each — including a full pause-then-
approve cycle for the medium-severity ticket, demonstrating the same
resume path the Streamlit dashboard's "Approve" button uses.

    python orchestrator/run_graph_demo.py
"""

import asyncio

import approvals
from graph import resume_incident, run_incident
from mcp_client import mcp_tools_session

# Low (auto-remediates), medium (pauses for approval -- resumed below),
# critical (escalates outright), and an unknown ticket ID (falls back
# to the default record, fails classification, and escalates even
# though its severity alone would otherwise qualify).
DEMO_TICKET_IDS = ["INC0012346", "INC0012345", "INC_DOES_NOT_EXIST"]

# This one pauses at the hard approval gate.
APPROVAL_DEMO_TICKET_ID = "INC0012354"


def _print(ticket_id: str, state) -> None:
    print(f"\n--- {ticket_id} ---")
    for line in state.log:
        print(f"  {line}")
    print(f"  route: {state.route}  |  decision: {state.decision}")


async def main() -> None:
    async with mcp_tools_session() as tools:
        for ticket_id in DEMO_TICKET_IDS:
            state = await run_incident(tools, ticket_id)
            _print(ticket_id, state)

        # --- Hard approval gate: pause, then approve ---
        paused = await run_incident(tools, APPROVAL_DEMO_TICKET_ID)
        _print(APPROVAL_DEMO_TICKET_ID, paused)
        print("  (paused -- this is exactly what shows up in the dashboard's pending-approvals queue)")

        pending = [
            row for row in approvals.list_pending()
            if row["ticket_id"] == APPROVAL_DEMO_TICKET_ID
        ][0]
        print(f"\n[Simulating dashboard: clicking Approve on thread {pending['thread_id']!r}]")

        resumed = await resume_incident(
            tools, pending["thread_id"], APPROVAL_DEMO_TICKET_ID, approved=True
        )
        _print(f"{APPROVAL_DEMO_TICKET_ID} (resumed)", resumed)


if __name__ == "__main__":
    asyncio.run(main())
