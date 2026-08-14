"""IT Ops MCP Server — IT Ops Multi-Agent Orchestrator
========================================================

Exposes three tools over MCP: check_ticket, get_runbook, and
run_remediation. See the project README for what each tool does, setup,
and MCP client configuration.
"""

from mcp.server.mcpserver import MCPServer

from db import get_ticket, init_db
from remediation_log import init_db as init_remediation_db
from remediation_log import run_remediation as log_remediation
from runbook_lookup import get_runbook_content

mcp = MCPServer("it-ops-tools")


@mcp.tool()
def check_ticket(ticket_id: str) -> dict:
    """Look up an IT support ticket by its ID and return its current
    details: title, description, severity, affected system, and status.

    Use this whenever you need information about a specific ticket.

    Args:
        ticket_id: The unique ticket identifier, e.g. 'INC0012345'.
    """
    return get_ticket(ticket_id)


@mcp.tool()
def get_runbook(issue_type: str) -> str:
    """Return the markdown runbook for a known IT issue type.

    Use this to look up diagnosis, remediation, and escalation steps for
    a category of issue (as opposed to a specific ticket).

    Args:
        issue_type: e.g. 'high_cpu', 'service_down', 'disk_full',
            'network_latency'. Spaces and hyphens are normalized, so
            'High CPU' and 'high-cpu' also match.
    """
    return get_runbook_content(issue_type)


@mcp.tool()
def run_remediation(action: str, target: str) -> dict:
    """Simulate running a remediation action against a target system.

    This is a MOCK executor — it never runs a real command. It only logs
    what it "would" do (e.g. "restarted service X on host Y") to an
    audit trail and returns that record. Use this to demonstrate or
    reason about a remediation step without making any real change.

    Args:
        action: A short description of the action, e.g. 'restart_service'.
        target: The system/host/service the action would apply to, e.g.
            'web-prod-cluster-03'.
    """
    return log_remediation(action, target)


if __name__ == "__main__":
    init_db()
    init_remediation_db()
    mcp.run(transport="stdio")
