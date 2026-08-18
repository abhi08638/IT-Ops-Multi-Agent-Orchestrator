"""orchestrator/tracing.py — Langfuse instrumentation for agent nodes,
routing decisions, and MCP tool calls.

Every IntakeAgent/TriageAgent/RemediationAgent/EscalationAgent.run(),
every decide_route() call, and every MCPTools tool call is traced
automatically via the decorators below — covering "every ticket,
decision, and tool call" regardless of whether the pipeline is driven
by the LangGraph StateGraph (graph.py) or manual chaining (run_demo.py).

Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY (and optionally
LANGFUSE_HOST, for self-hosted) in .env to actually send traces
somewhere. Without them, these decorators are no-ops — confirmed by
testing that a bare Langfuse client with no keys logs a warning and
disables itself rather than raising, but the no-op path here skips
calling into Langfuse at all, so there's no per-call log noise either.
"""

import os

from dotenv import load_dotenv

load_dotenv()

_LANGFUSE_ENABLED = bool(os.getenv("LANGFUSE_PUBLIC_KEY")) and bool(os.getenv("LANGFUSE_SECRET_KEY"))

if _LANGFUSE_ENABLED:
    from langfuse import observe

    def traced_agent(name: str):
        """Trace an Agent subclass's run() method."""
        return observe(name=name, as_type="agent")

    def traced_decision(name: str):
        """Trace a routing decision (decide_route())."""
        return observe(name=name, as_type="span")

    def traced_tool(name: str):
        """Trace an MCP tool call (MCPTools method)."""
        return observe(name=name, as_type="tool")

else:

    def _noop(name: str):
        def decorator(func):
            return func

        return decorator

    traced_agent = traced_decision = traced_tool = _noop
