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
3. **Remediation agent** — for low-severity tickets with a known safe
   action, calls `run_remediation` to execute it (mock execution).
   *(Built.)*
4. **Escalation agent** — marks an incident escalated for human review
   (high/critical severity, or no known safe action for the classified
   issue type) without ever calling `run_remediation`. *(Built.)*

Severity decides the path, via a hard three-tier gate (`decide_route()`
in [`orchestrator/agents.py`](orchestrator/agents.py)):

| Severity | Route | What happens |
|---|---|---|
| `low` | `remediate` | Auto-executes immediately |
| `medium` | `await_approval` | **Pauses** the graph and waits for a human "Approve" (see below) |
| `high` / `critical` | `escalate` | Never offered for auto-remediation at all |

Any issue type with no known safe action escalates outright, regardless
of severity.

See [`orchestrator/`](orchestrator) for the agent implementations.

## Hard approval gate

Medium-severity tickets don't silently execute and don't just get
logged as escalated — they genuinely **pause the LangGraph run**. This
uses LangGraph's `interrupt()` plus a persistent SQLite checkpointer
([`orchestrator/graph.py`](orchestrator/graph.py)), so the pause
survives past the end of the process that started it:

1. `approval_gate_node` records a pending approval
   ([`orchestrator/approvals.py`](orchestrator/approvals.py)) and calls
   `interrupt(...)` — the graph checkpoints its state and the run
   returns without completing.
2. Later, from a **different process** (the dashboard), `resume_incident()`
   reconnects to the same checkpoint file and resumes that exact
   thread with `Command(resume=approved)`.
3. If approved, the code right after the `interrupt()` call finally
   runs — the real `run_remediation` call that was withheld the first
   time around.

Verified live: paused first without ever touching `run_remediation`
(confirmed via `mcp_server/remediation_log.db`'s row count, not just
the returned state), then resumed from a completely separate MCP
session/subprocess and executed for real.

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
with a supervisor node that routes to remediation, the approval gate,
or escalation based on shared state:

```
intake -> triage -> supervisor --(remediate)-------> remediation    -> END
                               |-(await_approval)---> approval_gate -> END
                               \-(escalate)---------> escalation    -> END
```

```bash
python orchestrator/run_graph_demo.py
```

That demo runs the full pause-then-approve cycle for a medium-severity
ticket, simulating exactly what the dashboard's Approve button does.

The supervisor makes no MCP calls itself — it calls `decide_route()`, a
pure function shared with `RemediationAgent`/`EscalationAgent`/
`approval_gate_node`, to pick an edge. Each downstream node re-derives
the same deterministic decision before acting rather than trusting the
router blindly.

- [`orchestrator/state.py`](orchestrator/state.py) — `IncidentState`, the
  dataclass passed between agents/nodes (ticket, issue_type, severity,
  runbook, `route` the supervisor picked, final `decision`, and a
  running `log` of what happened and why). Used directly as the
  LangGraph `state_schema` — no TypedDict/Pydantic conversion needed.
- [`orchestrator/mcp_client.py`](orchestrator/mcp_client.py) — spawns
  `mcp_server/server.py` as a subprocess and wraps the MCP client
  session in a small typed `MCPTools` interface, so agents don't touch
  the MCP SDK directly (and are easy to unit-test against a fake).
- [`orchestrator/approvals.py`](orchestrator/approvals.py) — the
  pending-approval queue (`approvals.db`, gitignored): one row per
  paused thread, read/written by both the graph and the dashboard.
- [`orchestrator/incident_log.py`](orchestrator/incident_log.py) — a
  durable, upserted-by-thread record of every incident's outcome
  (`incidents.db`, gitignored) — the dashboard's "recent tickets" feed
  and auto-remediated/escalated counts come from here.
- [`orchestrator/tracing.py`](orchestrator/tracing.py) — Langfuse
  instrumentation (see Tracing, below).
- [`orchestrator/run_demo.py`](orchestrator/run_demo.py) /
  [`orchestrator/run_graph_demo.py`](orchestrator/run_graph_demo.py) —
  run either pipeline against sample tickets and print the decision
  trail for each.

## Dashboard

[`dashboard/app.py`](dashboard/app.py) is a one-page Streamlit view over
`approvals.db` and `incidents.db`:

- Auto-remediated / escalated / pending-approval counts
- The pending-approvals queue, each with an **Approve** button that
  calls `resume_incident()` for real — spawns a fresh MCP session and
  resumes the paused graph thread, same as the CLI demo
- A table of recent tickets processed

```bash
streamlit run dashboard/app.py
```

Verified by actually running it and clicking Approve in a browser: the
pending-approval card disappeared, "Auto-remediated" incremented, and
`mcp_server/remediation_log.db` gained a new row — not just a UI state
change.

## Project layout

```
agent-project/
├── mcp_server/            # MCP server: tools + their backing data
│   ├── server.py
│   ├── db.py
│   ├── runbook_lookup.py
│   ├── remediation_log.py
│   ├── data/
│   └── runbooks/
├── orchestrator/           # Agent nodes that call the MCP tools
│   ├── agents.py
│   ├── state.py
│   ├── mcp_client.py
│   ├── graph.py            # LangGraph StateGraph, supervisor routing, approval gate
│   ├── approvals.py        # pending-approval queue (approvals.db)
│   ├── incident_log.py     # durable incident feed (incidents.db)
│   ├── tracing.py          # Langfuse instrumentation (no-op without keys)
│   ├── run_demo.py
│   └── run_graph_demo.py
├── dashboard/               # Streamlit dashboard over approvals.db / incidents.db
│   └── app.py
├── tests/                   # unit tests for mcp_server/, orchestrator/, dashboard/
│   └── conftest.py          # shared sys.path setup + fake MCP client fixtures
├── requirements.txt
├── requirements-dev.txt
└── .gitignore
```

Each phase of the project gets its own top-level folder as it's built —
`mcp_server/`, `orchestrator/`, and `dashboard/` — so the repo (and its
commit history) reads as a clear timeline of what was built when.

## Setup

```bash
pip install -r requirements.txt
```

### Tracing (optional)

Every agent node, routing decision, and MCP tool call is instrumented
with [Langfuse](https://langfuse.com) via `orchestrator/tracing.py`. To
actually send traces somewhere, add to `.env`:

```
LANGFUSE_PUBLIC_KEY=your-public-key
LANGFUSE_SECRET_KEY=your-secret-key
LANGFUSE_HOST=https://cloud.langfuse.com   # or your self-hosted URL
```

Without these, tracing is a no-op — confirmed the app runs identically
either way; it just doesn't produce traces until you have an account.

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
