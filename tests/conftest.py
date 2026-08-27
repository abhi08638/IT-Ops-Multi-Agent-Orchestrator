"""Shared pytest setup: puts mcp_server/ and orchestrator/ on sys.path
(so test files can `import db` or `from agents import ...` directly,
without each repeating the same boilerplate), plus fixtures shared by
test_agents.py and test_graph.py.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "mcp_server"))
sys.path.insert(0, str(PROJECT_ROOT / "orchestrator"))

from mcp_client import RunbookNotFoundError  # noqa: E402 (needs sys.path set up first)


class FakeMCPTools:
    """Duck-types MCPTools without touching a real MCP server.

    - tickets: dict[ticket_id -> ticket dict], returned by check_ticket
    - runbooks: dict[issue_type -> runbook text]; missing keys raise
      RunbookNotFoundError, matching the real tool's behavior
    - run_remediation_calls: records every call for assertions
    """

    def __init__(self, tickets=None, runbooks=None):
        self.tickets = tickets or {}
        self.runbooks = runbooks or {}
        self.run_remediation_calls = []

    async def check_ticket(self, ticket_id: str) -> dict:
        return self.tickets[ticket_id]

    async def get_runbook(self, issue_type: str) -> str:
        if issue_type not in self.runbooks:
            raise RunbookNotFoundError(f"No runbook found for issue_type={issue_type!r}")
        return self.runbooks[issue_type]

    async def run_remediation(self, action: str, target: str) -> dict:
        self.run_remediation_calls.append((action, target))
        return {
            "id": len(self.run_remediation_calls),
            "status": "simulated",
            "action": action,
            "target": target,
            "message": f"Would run action {action!r} against target {target!r}.",
            "note": "Mock executor — no real command was run.",
        }


CRITICAL_TICKET = {
    "ticket_id": "INC0012345",
    "title": "Production web server unresponsive",
    "description": "Customers report intermittent 502 errors. Health checks failing.",
    "severity": "critical",
    "affected_system": "web-prod-cluster-03",
    "status": "open",
}

LOW_SEVERITY_TICKET = {
    "ticket_id": "INC0012346",
    "title": "User unable to reset VPN password",
    "description": "The self-service password reset portal returns a 500 error.",
    "severity": "low",
    "affected_system": "vpn-auth-service",
    "status": "open",
}

MEDIUM_SEVERITY_TICKET = {
    "ticket_id": "INC0012354",
    "title": "VPN throughput degraded during peak hours",
    "description": "Users report significantly slower VPN speeds. Latency roughly doubled.",
    "severity": "medium",
    "affected_system": "vpn-auth-service",
    "status": "open",
}

UNCLASSIFIABLE_TICKET = {
    "ticket_id": "INC9999999",
    "title": "Unspecified issue reported",
    "description": "No further detail was provided when the ticket was logged.",
    "severity": "medium",
    "affected_system": "unknown",
    "status": "open",
}
