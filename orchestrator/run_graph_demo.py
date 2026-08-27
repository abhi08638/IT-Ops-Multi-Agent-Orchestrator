"""orchestrator/run_graph_demo.py — run the LangGraph StateGraph
(intake -> triage -> supervisor -> remediation / approval_gate /
escalation) against a few sample tickets, against the real MCP server,
and print the decision trail for each.

    python orchestrator/run_graph_demo.py

The medium-severity tickets pause at the hard approval gate and are
left pending on purpose — run `streamlit run dashboard/app.py` and
click Approve there to resume them for real, rather than this script
resolving them itself.
"""

import asyncio

from graph import run_incident
from mcp_client import mcp_tools_session

# Low (auto-remediates), critical (escalates outright), and an unknown
# ticket ID (falls back to the default record, fails classification,
# and escalates even though its severity alone would otherwise qualify).
DEMO_TICKET_IDS = ["INC0012346", "INC0012345", "INC_DOES_NOT_EXIST"]

# Medium severity -- these pause at the hard approval gate and are left
# pending for the dashboard, not resumed by this script.
APPROVAL_DEMO_TICKET_IDS = ["INC0012354", "INC0012355"]


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

        for ticket_id in APPROVAL_DEMO_TICKET_IDS:
            state = await run_incident(tools, ticket_id)
            _print(ticket_id, state)

    print(
        f"\n{len(APPROVAL_DEMO_TICKET_IDS)} ticket(s) left pending approval. "
        "Run `streamlit run dashboard/app.py` and click Approve to resume them for real."
    )


if __name__ == "__main__":
    asyncio.run(main())
