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

## Intake MCP server

[`server.py`](server.py) exposes one tool, `check_ticket(ticket_id)`, backed
by a real SQLite query ([`db.py`](db.py)) over a seeded set of ~12 mock IT
tickets across a handful of systems (web cluster, VPN auth, billing API,
internal wiki, email gateway, backups, checkout, HR portal).

The seed data lives in [`data/tickets_seed.json`](data/tickets_seed.json)
(versioned, human-diffable). `tickets.db` itself is generated from that
fixture on first run and is not committed — delete it any time to reseed.

## Setup

```bash
pip install -r requirements.txt
```

Run the server directly (stdio transport):

```bash
python server.py
```

Or point an MCP client at it, e.g. in Claude Desktop's config:

```json
{
  "mcpServers": {
    "it-ops-intake": {
      "command": "python",
      "args": ["/absolute/path/to/server.py"]
    }
  }
}
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v
```
