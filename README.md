# IT Ops Multi-Agent Orchestrator

Concept: a multi-agent system that ingests IT incidents/tickets (from an
ITSM tool like ServiceNow), triages them, correlates against known issues or
runbooks, proposes a remediation action, and either auto-executes low-risk
fixes or escalates to a human — with every decision logged.

Each agent's capabilities are exposed as tools through an MCP server.

## Agents

1. **Intake agent** — pulls a ticket via `check_ticket`. *(Built.)*
2. **Triage agent** — classifies issue type from the ticket text (a
   deterministic keyword matcher for now, not RAG yet) and fetches the
   matching runbook via `get_runbook`. *(Built.)*
3. **Remediation agent** — for low/medium severity tickets with a known
   safe action, calls `run_remediation` to execute it (mock execution).
   *(Built.)*
4. **Escalation agent** — marks an incident escalated for human review
   (high/critical severity, or no known safe action for the classified
   issue type) without ever calling `run_remediation`. *(Built.)* Still
   just logs the escalation — routing it to an actual human-approval
   queue is a future step.

See [`orchestrator/`](orchestrator) for the agent implementations.

## MCP server

[`mcp_server/server.py`](mcp_server/server.py) currently exposes three
tools:

- **`check_ticket(ticket_id)`** — a real SQLite query
  ([`mcp_server/db.py`](mcp_server/db.py)) over a seeded set of ~12 mock
  IT tickets across a handful of systems (web cluster, VPN auth, billing
  API, internal wiki, email gateway, backups, checkout, HR portal). Seed
  data lives in
  [`mcp_server/data/tickets_seed.json`](mcp_server/data/tickets_seed.json)
  (versioned, human-diffable); `mcp_server/tickets.db` itself is
  generated from that fixture on first run and is not committed — delete
  it any time to reseed.
- **`get_runbook(issue_type)`** — returns the matching markdown runbook
  from [`mcp_server/runbooks/`](mcp_server/runbooks)
  ([`mcp_server/runbook_lookup.py`](mcp_server/runbook_lookup.py) does
  the lookup, normalizing spaces/hyphens/case). Currently a direct
  filename match against `high_cpu`, `service_down`, `disk_full`, and
  `network_latency` — the eventual Triage agent will do this via RAG
  instead, once there's a larger, less curated set of runbooks.
- **`run_remediation(action, target)`** — a **mock executor**
  ([`mcp_server/remediation_log.py`](mcp_server/remediation_log.py)). It
  never runs a real command; it only formats a description of what it
  "would" do (e.g. "restarted service X on host Y") and appends it to a
  persistent, queryable audit log (`mcp_server/remediation_log.db`,
  gitignored, generated at runtime). No
  `subprocess`/`os.system`/`eval`/`exec` appears anywhere near this
  tool, by design.

## Orchestrator

[`orchestrator/agents.py`](orchestrator/agents.py) implements the four
agents above as classes sharing a common `Agent.run(state) -> state`
interface. There are two ways they get chained together:

**Manual chaining** ([`orchestrator/run_demo.py`](orchestrator/run_demo.py)):

```python
async with mcp_tools_session() as tools:
    state = IncidentState(ticket_id="INC0012345")
    state = await IntakeAgent(tools).run(state)
    state = await TriageAgent(tools).run(state)
    state = await RemediationAgent(tools).run(state)  # decides AND acts
```

**LangGraph `StateGraph`** ([`orchestrator/graph.py`](orchestrator/graph.py)),
with a supervisor node that routes between remediation and escalation
based on shared state:

```
intake -> triage -> supervisor --(remediate)--> remediation -> END
                               \-(escalate)---> escalation  -> END
```

```bash
python orchestrator/run_graph_demo.py
```

The supervisor makes no MCP calls itself — it calls `decide_route()`, a
pure function shared with `RemediationAgent`/`EscalationAgent`, to pick
an edge. `RemediationAgent` only ever executes on the remediate branch;
`EscalationAgent` only ever escalates on the escalate branch — neither
node blindly trusts the router, since `decide_route()` is deterministic
and cheap to re-derive.

- [`orchestrator/state.py`](orchestrator/state.py) — `IncidentState`, the
  dataclass passed between agents/nodes (ticket, issue_type, severity,
  runbook, `route` the supervisor picked, final `decision`, and a
  running `log` of what happened and why). Used directly as the
  LangGraph `state_schema` — no TypedDict/Pydantic conversion needed.
- [`orchestrator/mcp_client.py`](orchestrator/mcp_client.py) — spawns
  `mcp_server/server.py` as a subprocess and wraps the MCP client
  session in a small typed `MCPTools` interface, so agents don't touch
  the MCP SDK directly (and are easy to unit-test against a fake).
- [`orchestrator/run_demo.py`](orchestrator/run_demo.py) /
  [`orchestrator/run_graph_demo.py`](orchestrator/run_graph_demo.py) —
  run either pipeline against sample tickets and print the decision
  trail for each.

## Project layout

```
agent-project/
├── mcp_server/           # MCP server: tools + their backing data
│   ├── server.py
│   ├── db.py
│   ├── runbook_lookup.py
│   ├── remediation_log.py
│   ├── data/
│   └── runbooks/
├── orchestrator/          # Agent nodes that call the MCP tools
│   ├── agents.py
│   ├── state.py
│   ├── mcp_client.py
│   ├── graph.py           # LangGraph StateGraph + supervisor routing
│   ├── run_demo.py
│   └── run_graph_demo.py
├── tests/                 # unit tests for mcp_server/ and orchestrator/
│   └── conftest.py        # shared sys.path setup + fake MCP client fixtures
├── requirements.txt
├── requirements-dev.txt
└── .gitignore
```

Each phase of the project gets its own top-level folder as it's built —
`mcp_server/` and `orchestrator/` today, with `dashboard/` planned for a
later phase — so the repo (and its commit history) reads as a clear
timeline of what was built when.

## Setup

```bash
pip install -r requirements.txt
```

Run the server directly (stdio transport):

```bash
python mcp_server/server.py
```

Or point an MCP client at it, e.g. in Claude Desktop's config:

```json
{
  "mcpServers": {
    "it-ops-tools": {
      "command": "python",
      "args": ["/absolute/path/to/mcp_server/server.py"]
    }
  }
}
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```
