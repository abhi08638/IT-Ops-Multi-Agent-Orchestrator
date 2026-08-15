"""orchestrator/run_graph_demo.py — run the LangGraph StateGraph
(intake -> triage -> supervisor -> remediation-or-escalation) against a
few sample tickets, against the real MCP server, and print the decision
trail for each.

    python orchestrator/run_graph_demo.py
"""

import asyncio

from graph import run_incident
from mcp_client import mcp_tools_session

# One low-severity (auto-remediates), one critical (escalates), and one
# unknown ticket ID (falls back to the default record, fails
# classification, and escalates even though its severity alone would
# otherwise qualify).
DEMO_TICKET_IDS = ["INC0012346", "INC0012345", "INC_DOES_NOT_EXIST"]


async def main() -> None:
    async with mcp_tools_session() as tools:
        for ticket_id in DEMO_TICKET_IDS:
            state = await run_incident(tools, ticket_id)
            print(f"\n--- {ticket_id} ---")
            for line in state.log:
                print(f"  {line}")
            print(f"  route: {state.route}  |  decision: {state.decision}")


if __name__ == "__main__":
    asyncio.run(main())
