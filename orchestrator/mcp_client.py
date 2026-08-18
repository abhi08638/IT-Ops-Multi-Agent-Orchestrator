"""orchestrator/mcp_client.py — thin async wrapper over an MCP client
session, typed to the three tools exposed by mcp_server/server.py.

Agent nodes depend on the MCPTools interface below, not on the MCP
client SDK directly, so they're easy to unit-test with a fake in place
of a real subprocess connection (see tests/test_agents.py).
"""

import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from tracing import traced_tool

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_PATH = PROJECT_ROOT / "mcp_server" / "server.py"


class RunbookNotFoundError(Exception):
    """Raised when get_runbook has no runbook matching the issue_type."""


def _text(result) -> str:
    return "".join(block.text for block in result.content if hasattr(block, "text"))


class MCPTools:
    """Typed wrapper over an active MCP ClientSession's IT-ops tools."""

    def __init__(self, session: ClientSession):
        self._session = session

    @traced_tool("check_ticket")
    async def check_ticket(self, ticket_id: str) -> dict:
        result = await self._session.call_tool("check_ticket", {"ticket_id": ticket_id})
        text = _text(result)
        if result.is_error:
            raise RuntimeError(f"check_ticket failed: {text}")
        return json.loads(text)

    @traced_tool("get_runbook")
    async def get_runbook(self, issue_type: str) -> str:
        result = await self._session.call_tool("get_runbook", {"issue_type": issue_type})
        text = _text(result)
        if result.is_error:
            raise RunbookNotFoundError(text)
        return text

    @traced_tool("run_remediation")
    async def run_remediation(self, action: str, target: str) -> dict:
        result = await self._session.call_tool(
            "run_remediation", {"action": action, "target": target}
        )
        text = _text(result)
        if result.is_error:
            raise RuntimeError(f"run_remediation failed: {text}")
        return json.loads(text)


@asynccontextmanager
async def mcp_tools_session(python_executable: str | None = None):
    """Spawn the it-ops-tools MCP server as a subprocess and yield a
    connected MCPTools client.

        async with mcp_tools_session() as tools:
            ticket = await tools.check_ticket("INC0012345")

    One session is meant to be reused across an entire Intake -> Triage
    -> Remediation run, rather than reconnecting per tool call.
    """
    params = StdioServerParameters(
        command=python_executable or sys.executable,
        args=[str(SERVER_PATH)],
        cwd=str(PROJECT_ROOT),
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield MCPTools(session)
