# IT Ops Multi-Agent Orchestrator

Concept: a multi-agent system that ingests IT incidents/tickets (from an
ITSM tool like ServiceNow), triages them, correlates against known issues or
runbooks, proposes a remediation action, and either auto-executes low-risk
fixes or escalates to a human — with every decision logged.

Each agent's capabilities are exposed as tools through an MCP server.

## Agents

1. **Intake agent** — looks up a ticket by ID. *(Built — see below.)*
2. **Triage agent** — classifies severity/category, backed by RAG over a
   folder of markdown runbooks.
3. **Remediation agent** — proposes a fix and can execute a safe, mocked
   command.
4. **Escalation / reporting agent** — the safety gate: low-risk fixes get
   summarized and auto-executed; anything high-severity or high-risk routes
   to a human for approval instead.

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

## Project layout

```
agent-project/
├── mcp_server/          # MCP server: tools + their backing data
│   ├── server.py
│   ├── db.py
│   ├── runbook_lookup.py
│   ├── remediation_log.py
│   ├── data/
│   └── runbooks/
├── tests/                # unit tests for everything under mcp_server/
├── requirements.txt
├── requirements-dev.txt
└── .gitignore
```

Each phase of the project gets its own top-level folder as it's built —
`mcp_server/` today, with `orchestrator/` and `dashboard/` planned for
later phases — so the repo (and its commit history) reads as a clear
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
