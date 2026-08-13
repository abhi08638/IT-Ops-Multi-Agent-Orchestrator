"""Intake MCP Server — IT Ops Multi-Agent Orchestrator
========================================================

Exposes `check_ticket` as an MCP tool, backed by a real SQLite query
(see db.py) over a seeded set of mock IT tickets. Any MCP client — Claude
Desktop, Claude Code, or a custom client — can connect to this server over
stdio and call the tool.

Run directly for local testing:
    python server.py

Or point an MCP client at it, e.g. in Claude Desktop's config:
    {
      "mcpServers": {
        "it-ops-intake": {
          "command": "python",
          "args": ["/absolute/path/to/server.py"]
        }
      }
    }
"""

from mcp.server.mcpserver import MCPServer

from db import get_ticket, init_db

mcp = MCPServer("it-ops-intake")


@mcp.tool()
def check_ticket(ticket_id: str) -> dict:
    """Look up an IT support ticket by its ID and return its current
    details: title, description, severity, affected system, and status.

    Use this whenever you need information about a specific ticket.

    Args:
        ticket_id: The unique ticket identifier, e.g. 'INC0012345'.
    """
    return get_ticket(ticket_id)


if __name__ == "__main__":
    init_db()
    mcp.run(transport="stdio")
