"""orchestrator/run_demo.py — run the Intake -> Triage -> Remediation
pipeline against a couple of sample tickets, against the real MCP
server, and print what each agent decided and why.

    python orchestrator/run_demo.py
"""

import asyncio

from agents import IntakeAgent, RemediationAgent, TriageAgent
from mcp_client import mcp_tools_session
from state import IncidentState

# A low-severity ticket (auto-remediates) and a critical one (escalates).
DEMO_TICKET_IDS = ["INC0012346", "INC0012345"]


async def run_pipeline(tools, ticket_id: str) -> IncidentState:
    state = IncidentState(ticket_id=ticket_id)
    state = await IntakeAgent(tools).run(state)
    state = await TriageAgent(tools).run(state)
    state = await RemediationAgent(tools).run(state)
    return state


async def main() -> None:
    async with mcp_tools_session() as tools:
        for ticket_id in DEMO_TICKET_IDS:
            state = await run_pipeline(tools, ticket_id)
            print(f"\n--- {ticket_id} ---")
            for line in state.log:
                print(f"  {line}")
            print(f"  decision: {state.decision}")


if __name__ == "__main__":
    asyncio.run(main())
